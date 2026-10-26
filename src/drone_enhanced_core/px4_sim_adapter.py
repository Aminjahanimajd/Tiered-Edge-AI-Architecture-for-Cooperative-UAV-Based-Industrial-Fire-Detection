"""Pure safety and geometry contracts for the simulator-only PX4 adapter."""

from __future__ import annotations

import math
from typing import NamedTuple


SIMULATION_ACKNOWLEDGEMENT = "I_ACKNOWLEDGE_PX4_SITL_ONLY"
VEHICLE_IDENTITIES = {
    "sentinel": {"namespace": "/sentinel", "system_id": 2},
    "scout": {"namespace": "/scout", "system_id": 3},
}
ALLOWED_INPUT_SUFFIXES = {
    "/fmu/in/offboard_control_mode",
    "/fmu/in/trajectory_setpoint",
    "/fmu/in/vehicle_command",
}


class EnuPosition(NamedTuple):
    east_m: float
    north_m: float
    up_m: float


class NedPosition(NamedTuple):
    north_m: float
    east_m: float
    down_m: float


def _finite_position(name: str, position, expected_type):
    if not isinstance(position, expected_type):
        raise TypeError(f"{name} must be {expected_type.__name__}")
    if not all(math.isfinite(float(value)) for value in position):
        raise ValueError(f"{name} components must be finite")
    return position


def absolute_enu_to_local_ned(target: EnuPosition, home: EnuPosition) -> NedPosition:
    """Convert scenario-global ENU truth to a vehicle-home-relative NED setpoint."""
    target = _finite_position("target", target, EnuPosition)
    home = _finite_position("home", home, EnuPosition)
    return NedPosition(
        north_m=target.north_m - home.north_m,
        east_m=target.east_m - home.east_m,
        down_m=-(target.up_m - home.up_m),
    )


def setpoint_reached(
    actual: NedPosition,
    target: NedPosition,
    horizontal_tolerance_m: float = 0.6,
    vertical_tolerance_m: float = 0.4,
) -> bool:
    actual = _finite_position("actual", actual, NedPosition)
    target = _finite_position("target", target, NedPosition)
    horizontal_tolerance_m = float(horizontal_tolerance_m)
    vertical_tolerance_m = float(vertical_tolerance_m)
    if horizontal_tolerance_m <= 0 or vertical_tolerance_m <= 0:
        raise ValueError("position tolerances must be positive")
    horizontal_error = math.hypot(
        actual.north_m - target.north_m,
        actual.east_m - target.east_m,
    )
    vertical_error = abs(actual.down_m - target.down_m)
    return (
        horizontal_error <= horizontal_tolerance_m
        and vertical_error <= vertical_tolerance_m
    )


def landing_position_valid(
    actual: NedPosition,
    maximum_horizontal_error_m: float = 2.0,
    maximum_vertical_error_m: float = 0.5,
) -> bool:
    """Check final landed position against the vehicle-local home origin."""
    return setpoint_reached(
        actual,
        NedPosition(0.0, 0.0, 0.0),
        maximum_horizontal_error_m,
        maximum_vertical_error_m,
    )


class SimulationCommandGuard:
    """Fail closed unless command identity and SITL-only acknowledgement match."""

    def __init__(self, acknowledgement: str, vehicle_id: str):
        if acknowledgement != SIMULATION_ACKNOWLEDGEMENT:
            raise PermissionError("explicit PX4 SITL-only acknowledgement is required")
        if vehicle_id not in VEHICLE_IDENTITIES:
            raise ValueError(f"unknown simulated vehicle: {vehicle_id}")
        self.vehicle_id = vehicle_id
        self.identity = VEHICLE_IDENTITIES[vehicle_id]

    def topic(self, suffix: str) -> str:
        if suffix not in ALLOWED_INPUT_SUFFIXES:
            raise PermissionError(f"input topic is not allowlisted: {suffix}")
        return self.identity["namespace"] + suffix

    def validate_status_identity(self, system_id: int) -> None:
        if int(system_id) != self.identity["system_id"]:
            raise PermissionError(
                f"{self.vehicle_id} expected PX4 system ID "
                f"{self.identity['system_id']}, received {system_id}"
            )

    def validate_target(
        self,
        target: EnuPosition,
        width_m: float,
        length_m: float,
        maximum_altitude_m: float,
        minimum_east_m: float = 0.0,
        minimum_north_m: float = 0.0,
    ) -> EnuPosition:
        target = _finite_position("target", target, EnuPosition)
        width_m = float(width_m)
        length_m = float(length_m)
        maximum_altitude_m = float(maximum_altitude_m)
        minimum_east_m = float(minimum_east_m)
        minimum_north_m = float(minimum_north_m)
        if min(width_m, length_m, maximum_altitude_m) <= 0:
            raise ValueError("scenario bounds must be positive")
        maximum_east_m = minimum_east_m + width_m
        maximum_north_m = minimum_north_m + length_m
        if not (minimum_east_m <= target.east_m <= maximum_east_m):
            raise ValueError("target east coordinate is outside the scenario")
        if not (minimum_north_m <= target.north_m <= maximum_north_m):
            raise ValueError("target north coordinate is outside the scenario")
        if not (0 <= target.up_m <= maximum_altitude_m):
            raise ValueError("target altitude is outside the scenario")
        return target
