"""Safety-locked local-frame mission planning for offline validation only."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum


class ActuationBlocked(RuntimeError):
    """Raised whenever an actuator method is called on the dry-run adapter."""


class MissionMode(Enum):
    SAFE_IDLE = "SAFE_IDLE"
    SEARCHING = "SEARCHING"
    HOLDING_FOR_VERIFICATION = "HOLDING_FOR_VERIFICATION"
    CONFIRMED_HOLD = "CONFIRMED_HOLD"


@dataclass(frozen=True)
class LocalWaypoint:
    """Proposed waypoint in an arbitrary local ENU frame, never geographic."""

    east_m: float
    north_m: float
    altitude_m: float
    yaw_deg: float = 0.0

    def __post_init__(self) -> None:
        values = (self.east_m, self.north_m, self.altitude_m, self.yaw_deg)
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("waypoint values must be finite")
        if self.altitude_m <= 0.0:
            raise ValueError("proposed altitude must be positive")


def lawnmower_search_plan(
    width_m: float,
    length_m: float,
    lane_spacing_m: float,
    altitude_m: float,
) -> tuple[LocalWaypoint, ...]:
    """Build a deterministic rectangular search preview in a local ENU frame."""

    values = (width_m, length_m, lane_spacing_m, altitude_m)
    if not all(math.isfinite(float(value)) and float(value) > 0.0 for value in values):
        raise ValueError("search dimensions, spacing, and altitude must be finite and positive")
    lane_count = int(math.ceil(float(width_m) / float(lane_spacing_m))) + 1
    north_values = [min(index * float(lane_spacing_m), float(width_m)) for index in range(lane_count)]
    if north_values[-1] != float(width_m):
        north_values.append(float(width_m))
    waypoints = []
    for index, north in enumerate(north_values):
        east = float(length_m) if index % 2 == 0 else 0.0
        yaw = 90.0 if index % 2 == 0 else -90.0
        waypoints.append(LocalWaypoint(east, north, float(altitude_m), yaw))
    return tuple(waypoints)


class SafetyLockedFlightAdapter:
    """Records previews and rejects every command that could move a vehicle."""

    def __init__(self) -> None:
        self.preview_records: list[dict] = []
        self.blocked_attempts: list[str] = []

    def preview_waypoint(self, waypoint: LocalWaypoint, sequence: int) -> dict:
        if not isinstance(waypoint, LocalWaypoint):
            raise TypeError("waypoint must be a LocalWaypoint")
        record = {
            "kind": "PREVIEW_ONLY",
            "sequence": int(sequence),
            "frame": "arbitrary_local_enu",
            "waypoint": asdict(waypoint),
            "armed": False,
            "transmitted_to_vehicle": False,
        }
        self.preview_records.append(record)
        return record

    def _block(self, command: str) -> None:
        self.blocked_attempts.append(command)
        raise ActuationBlocked(f"{command} is disabled by the dry-run safety interlock")

    def arm(self) -> None:
        self._block("arm")

    def takeoff(self, altitude_m: float) -> None:
        self._block("takeoff")

    def goto(self, waypoint: LocalWaypoint) -> None:
        self._block("goto")

    def set_velocity(self, east_mps: float, north_mps: float, up_mps: float) -> None:
        self._block("set_velocity")


class DryRunMissionController:
    """Preview search and verification state transitions without an actuator path."""

    def __init__(self, waypoints: tuple[LocalWaypoint, ...], adapter: SafetyLockedFlightAdapter):
        if not waypoints:
            raise ValueError("at least one waypoint is required")
        if not all(isinstance(item, LocalWaypoint) for item in waypoints):
            raise TypeError("all waypoints must be LocalWaypoint values")
        if not isinstance(adapter, SafetyLockedFlightAdapter):
            raise TypeError("a SafetyLockedFlightAdapter is required")
        self.waypoints = waypoints
        self.adapter = adapter
        self.mode = MissionMode.SAFE_IDLE
        self.next_waypoint = 0
        self.active_event_id: str | None = None
        self.transitions: list[dict] = []

    def start_search_preview(self) -> None:
        if self.mode != MissionMode.SAFE_IDLE:
            raise RuntimeError("search preview can start only from SAFE_IDLE")
        self.mode = MissionMode.SEARCHING
        self.transitions.append({"event": "start_search_preview", "mode": self.mode.value})

    def preview_next_waypoint(self) -> dict:
        if self.mode != MissionMode.SEARCHING:
            raise RuntimeError("waypoint preview is allowed only while SEARCHING")
        waypoint = self.waypoints[self.next_waypoint]
        record = self.adapter.preview_waypoint(waypoint, self.next_waypoint)
        self.next_waypoint = (self.next_waypoint + 1) % len(self.waypoints)
        return record

    def begin_verification_hold(self, event_id: str) -> None:
        if self.mode != MissionMode.SEARCHING:
            raise RuntimeError("verification hold requires SEARCHING mode")
        event_id = str(event_id).strip()
        if not event_id:
            raise ValueError("event_id cannot be empty")
        self.active_event_id = event_id
        self.mode = MissionMode.HOLDING_FOR_VERIFICATION
        self.transitions.append(
            {"event": "begin_verification_hold", "event_id": event_id, "mode": self.mode.value}
        )

    def apply_verdict(self, event_id: str, verdict: str) -> None:
        if self.mode != MissionMode.HOLDING_FOR_VERIFICATION:
            raise RuntimeError("no event is awaiting a verdict")
        if str(event_id) != self.active_event_id:
            raise ValueError("verdict event ID does not match the active event")
        normalized = str(verdict).upper()
        if normalized == "CONFIRMED":
            self.mode = MissionMode.CONFIRMED_HOLD
        elif normalized in {"REJECTED", "TIMEOUT", "ERROR"}:
            self.mode = MissionMode.SEARCHING
        else:
            raise ValueError("unsupported verdict")
        self.transitions.append(
            {"event": "apply_verdict", "event_id": str(event_id), "verdict": normalized, "mode": self.mode.value}
        )
        self.active_event_id = None

    def reset_confirmed_hold(self) -> None:
        if self.mode != MissionMode.CONFIRMED_HOLD:
            raise RuntimeError("controller is not in CONFIRMED_HOLD")
        self.mode = MissionMode.SAFE_IDLE
        self.transitions.append({"event": "reset_confirmed_hold", "mode": self.mode.value})
