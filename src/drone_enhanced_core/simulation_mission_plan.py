"""Deterministic geometry for the dual-PX4 hierarchical mission.

All positions in this module are simulator scenario truth in local ENU. They
must never be interpreted as vision-derived or geographic localization.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import NamedTuple

from drone_enhanced_core.px4_sim_adapter import EnuPosition


class Geofence(NamedTuple):
    minimum_east_m: float
    maximum_east_m: float
    minimum_north_m: float
    maximum_north_m: float
    maximum_altitude_m: float

    def require(self, position: EnuPosition) -> EnuPosition:
        if not isinstance(position, EnuPosition):
            raise TypeError("position must be EnuPosition")
        if not all(math.isfinite(float(value)) for value in position):
            raise ValueError("position components must be finite")
        if not self.minimum_east_m <= position.east_m <= self.maximum_east_m:
            raise ValueError("position east coordinate is outside the geofence")
        if not self.minimum_north_m <= position.north_m <= self.maximum_north_m:
            raise ValueError("position north coordinate is outside the geofence")
        if not 0.0 <= position.up_m <= self.maximum_altitude_m:
            raise ValueError("position altitude is outside the geofence")
        return position


class MissionWaypoint(NamedTuple):
    vehicle_id: str
    purpose: str
    index: int
    position_enu: EnuPosition


class HierarchicalMissionPlan(NamedTuple):
    scenario_id: str
    event_id: str
    target_id: str
    expected_verdict: str
    sentinel_home: EnuPosition
    scout_home: EnuPosition
    sentinel_patrol: tuple
    sentinel_hold: MissionWaypoint
    scout_standoff: MissionWaypoint
    sentinel_rtl: MissionWaypoint
    scout_rtl: MissionWaypoint
    claim_boundary: str


def _finite(name, value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _position(values, name):
    if not isinstance(values, list) or len(values) != 3:
        raise ValueError(f"{name} must contain exactly three ENU values")
    return EnuPosition(*(_finite(name, value) for value in values))


def _axis_points(start, stop, spacing):
    start, stop, spacing = map(float, (start, stop, spacing))
    if stop <= start or spacing <= 0:
        raise ValueError("patrol bounds and lane spacing must be positive")
    points = []
    value = start
    while value < stop:
        points.append(value)
        value += spacing
    points.append(stop)
    return tuple(points)


def lawnmower_waypoints(bounds, altitude_m, lane_spacing_m):
    """Return a deterministic east-lane, alternating-north patrol."""
    altitude_m = _finite("altitude_m", altitude_m)
    east_values = _axis_points(
        bounds["minimum_east_m"],
        bounds["maximum_east_m"],
        lane_spacing_m,
    )
    south = _finite("minimum_north_m", bounds["minimum_north_m"])
    north = _finite("maximum_north_m", bounds["maximum_north_m"])
    if north <= south:
        raise ValueError("maximum north must exceed minimum north")
    waypoints = []
    for lane, east in enumerate(east_values):
        north_values = (south, north) if lane % 2 == 0 else (north, south)
        for north_value in north_values:
            waypoints.append(EnuPosition(east, north_value, altitude_m))
    return tuple(waypoints)


def standoff_position(target, scout_home, distance_m, altitude_m):
    """Place Scout on the target-to-home ray at a bounded horizontal distance."""
    distance_m = _finite("distance_m", distance_m)
    altitude_m = _finite("altitude_m", altitude_m)
    if distance_m <= 0:
        raise ValueError("standoff distance must be positive")
    east_delta = scout_home.east_m - target.east_m
    north_delta = scout_home.north_m - target.north_m
    norm = math.hypot(east_delta, north_delta)
    if norm == 0:
        east_delta, north_delta, norm = -1.0, 0.0, 1.0
    return EnuPosition(
        target.east_m + distance_m * east_delta / norm,
        target.north_m + distance_m * north_delta / norm,
        altitude_m,
    )


def _geofence(environment):
    return Geofence(
        _finite("minimum_east_m", environment["minimum_east_m"]),
        _finite("maximum_east_m", environment["maximum_east_m"]),
        _finite("minimum_north_m", environment["minimum_north_m"]),
        _finite("maximum_north_m", environment["maximum_north_m"]),
        _finite("maximum_altitude_m", environment["maximum_altitude_m"]),
    )


def build_hierarchical_plan(configuration, event_id):
    if int(configuration.get("schema_version", 0)) != 2:
        raise ValueError("mission planning requires scenario schema version 2")
    if configuration.get("coordinate_frame") != "local_enu_simulator_ground_truth":
        raise ValueError("mission coordinates must remain simulator local ENU truth")
    environment = configuration["environment"]
    mission = configuration["mission"]
    fence = _geofence(environment)
    highest_safe_altitude = _finite(
        "highest_modeled_obstacle_m", environment["highest_modeled_obstacle_m"]
    ) + _finite(
        "minimum_vertical_clearance_m",
        environment["minimum_vertical_clearance_m"],
    )
    sentinel_altitude = _finite(
        "sentinel_patrol_altitude_m", mission["sentinel_patrol_altitude_m"]
    )
    scout_altitude = _finite(
        "scout_transit_altitude_m", mission["scout_transit_altitude_m"]
    )
    if sentinel_altitude < highest_safe_altitude:
        raise ValueError("Sentinel patrol altitude violates modeled clearance")
    if scout_altitude < highest_safe_altitude:
        raise ValueError("Scout transit altitude violates modeled clearance")

    by_event = {row["event_id"]: row for row in configuration["targets"]}
    if event_id not in by_event:
        raise ValueError(f"unknown scenario event: {event_id}")
    target_row = by_event[event_id]
    target = _position(target_row["position_enu_m"], "target position")
    sentinel_home = _position(
        configuration["vehicles"]["sentinel"]["home_enu_m"], "Sentinel home"
    )
    scout_home = _position(
        configuration["vehicles"]["scout"]["home_enu_m"], "Scout home"
    )
    for position in (target, sentinel_home, scout_home):
        fence.require(position)

    patrol_positions = lawnmower_waypoints(
        mission["patrol_bounds_enu_m"],
        sentinel_altitude,
        mission["lane_spacing_m"],
    )
    for position in patrol_positions:
        fence.require(position)
    sentinel_patrol = tuple(
        MissionWaypoint("sentinel", "PATROL", index, position)
        for index, position in enumerate(patrol_positions)
    )
    minimum_sentinel_standoff = _finite(
        "sentinel_hazard_standoff_distance_m",
        mission.get("sentinel_hazard_standoff_distance_m", 0.0),
    )
    eligible_hold_indices = [
        index for index, position in enumerate(patrol_positions)
        if math.hypot(
            position.east_m - target.east_m,
            position.north_m - target.north_m,
        ) >= minimum_sentinel_standoff
    ]
    if not eligible_hold_indices:
        raise ValueError("no Sentinel patrol waypoint satisfies hazard standoff")
    hold_index = min(
        eligible_hold_indices,
        key=lambda index: math.hypot(
            patrol_positions[index].east_m - target.east_m,
            patrol_positions[index].north_m - target.north_m,
        ),
    )
    sentinel_hold = MissionWaypoint(
        "sentinel", "SUSPECT_HOLD", hold_index, patrol_positions[hold_index]
    )

    standoff_distance = _finite(
        "scout_standoff_distance_m", mission["scout_standoff_distance_m"]
    )
    exclusion = _finite(
        "horizontal_exclusion_radius_m",
        target_row["horizontal_exclusion_radius_m"],
    )
    if standoff_distance <= exclusion:
        raise ValueError("Scout standoff must exceed the target exclusion radius")
    scout_standoff_position = standoff_position(
        target, scout_home, standoff_distance, scout_altitude
    )
    fence.require(scout_standoff_position)

    sentinel_rtl_position = EnuPosition(
        sentinel_home.east_m, sentinel_home.north_m, sentinel_altitude
    )
    scout_rtl_position = EnuPosition(
        scout_home.east_m, scout_home.north_m, scout_altitude
    )
    fence.require(sentinel_rtl_position)
    fence.require(scout_rtl_position)
    verdict = str(target_row["expected_verdict"]).upper()
    if verdict not in {"CONFIRMED", "REJECTED"}:
        raise ValueError("expected verdict must be CONFIRMED or REJECTED")
    return HierarchicalMissionPlan(
        scenario_id=environment["id"],
        event_id=event_id,
        target_id=target_row["target_id"],
        expected_verdict=verdict,
        sentinel_home=sentinel_home,
        scout_home=scout_home,
        sentinel_patrol=sentinel_patrol,
        sentinel_hold=sentinel_hold,
        scout_standoff=MissionWaypoint(
            "scout", "VERIFYING", 0, scout_standoff_position
        ),
        sentinel_rtl=MissionWaypoint(
            "sentinel", "RTL", 0, sentinel_rtl_position
        ),
        scout_rtl=MissionWaypoint("scout", "RTL", 0, scout_rtl_position),
        claim_boundary=(
            "Development geometry from simulator scenario truth; not "
            "vision-derived localization or physical flight validation."
        ),
    )


def load_hierarchical_plan(path, event_id):
    path = Path(path)
    configuration = json.loads(path.read_text(encoding="utf-8"))
    return build_hierarchical_plan(configuration, event_id)
