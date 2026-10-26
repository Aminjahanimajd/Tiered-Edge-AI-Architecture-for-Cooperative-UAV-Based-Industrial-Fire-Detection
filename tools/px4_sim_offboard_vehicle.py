#!/usr/bin/env python3
"""Run one bounded SITL-only PX4 offboard takeoff, translation, and landing."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

import rclpy
from px4_msgs.msg import (
    OffboardControlMode,
    TrajectorySetpoint,
    VehicleCommand,
    VehicleCommandAck,
    VehicleLandDetected,
    VehicleLocalPosition,
    VehicleStatus,
)
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from drone_enhanced_core.px4_sim_adapter import (
    SIMULATION_ACKNOWLEDGEMENT,
    EnuPosition,
    NedPosition,
    SimulationCommandGuard,
    absolute_enu_to_local_ned,
    setpoint_reached,
)


PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)


class OffboardVehicleProbe(Node):
    """A finite simulator probe; it refuses every non-allowlisted input topic."""

    def __init__(self, args):
        super().__init__(f"{args.vehicle_id}_sitl_offboard_probe")
        acknowledgement = os.environ.get("DRONE_ENHANCED_SIMULATION_ONLY", "")
        self.guard = SimulationCommandGuard(acknowledgement, args.vehicle_id)
        self.vehicle_id = args.vehicle_id
        self.expected_system_id = self.guard.identity["system_id"]
        self.home = EnuPosition(*args.home_enu)
        self.target_enu = self.guard.validate_target(
            EnuPosition(*args.target_enu),
            args.world_width_m,
            args.world_length_m,
            args.maximum_altitude_m,
        )
        self.target_ned = absolute_enu_to_local_ned(self.target_enu, self.home)
        self.takeoff_ned = NedPosition(0.0, 0.0, -float(args.takeoff_altitude_m))
        self.hold_s = float(args.hold_s)
        self.total_timeout_s = float(args.total_timeout_s)
        self.output = Path(args.output)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        if self.output.exists():
            raise FileExistsError(self.output)
        self.stream = self.output.open("x", encoding="utf-8", newline="\n")

        self.started_monotonic = time.monotonic()
        self.phase_started = self.started_monotonic
        self.phase = "WAIT_TELEMETRY"
        self.status = None
        self.position = None
        self.land = None
        self.last_px4_timestamp_us = 0
        self.prime_count = 0
        self.command_attempts = {}
        self.last_arm_attempt_monotonic = 0.0
        self.finished = False
        self.success = False
        self.failure_reason = None
        self.identity_verified = False

        prefix = self.guard.identity["namespace"]
        self.offboard_pub = self.create_publisher(
            OffboardControlMode,
            self.guard.topic("/fmu/in/offboard_control_mode"),
            PX4_QOS,
        )
        self.setpoint_pub = self.create_publisher(
            TrajectorySetpoint,
            self.guard.topic("/fmu/in/trajectory_setpoint"),
            PX4_QOS,
        )
        self.command_pub = self.create_publisher(
            VehicleCommand,
            self.guard.topic("/fmu/in/vehicle_command"),
            PX4_QOS,
        )
        self.create_subscription(
            VehicleStatus,
            prefix + "/fmu/out/vehicle_status_v1",
            self._status_callback,
            PX4_QOS,
        )
        self.create_subscription(
            VehicleLocalPosition,
            prefix + "/fmu/out/vehicle_local_position_v1",
            self._position_callback,
            PX4_QOS,
        )
        self.create_subscription(
            VehicleLandDetected,
            prefix + "/fmu/out/vehicle_land_detected",
            self._land_callback,
            PX4_QOS,
        )
        self.create_subscription(
            VehicleCommandAck,
            prefix + "/fmu/out/vehicle_command_ack",
            self._ack_callback,
            PX4_QOS,
        )
        self.timer = self.create_timer(0.1, self._tick)
        self._log(
            "START",
            home_enu=list(self.home),
            target_enu=list(self.target_enu),
            target_local_ned=list(self.target_ned),
            safety_state="PX4 SITL only; no physical transport or interface",
        )

    def _now_us(self):
        return self.get_clock().now().nanoseconds // 1000

    def _log(self, event, **values):
        row = {
            "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "monotonic_ns": time.monotonic_ns(),
            "px4_timestamp_us": self.last_px4_timestamp_us,
            "vehicle_id": self.vehicle_id,
            "phase": self.phase,
            "event": event,
        }
        row.update(values)
        self.stream.write(json.dumps(row, sort_keys=True) + "\n")
        self.stream.flush()

    def _status_callback(self, message):
        try:
            self.guard.validate_status_identity(message.system_id)
            if not self.identity_verified:
                self.identity_verified = True
                self._log("IDENTITY_VERIFIED", system_id=int(message.system_id))
            self.status = message
            self.last_px4_timestamp_us = max(
                self.last_px4_timestamp_us, int(message.timestamp)
            )
        except BaseException as exc:
            self._fail(f"identity validation failed: {exc}")

    def _position_callback(self, message):
        self.position = NedPosition(float(message.x), float(message.y), float(message.z))
        self.last_px4_timestamp_us = max(
            self.last_px4_timestamp_us, int(message.timestamp)
        )

    def _land_callback(self, message):
        self.land = message
        self.last_px4_timestamp_us = max(
            self.last_px4_timestamp_us, int(message.timestamp)
        )

    def _ack_callback(self, message):
        self.last_px4_timestamp_us = max(
            self.last_px4_timestamp_us, int(message.timestamp)
        )
        self._log(
            "VEHICLE_COMMAND_ACK",
            command=int(message.command),
            result=int(message.result),
            target_system=int(message.target_system),
            target_component=int(message.target_component),
        )

    def _transition(self, phase, reason):
        source = self.phase
        self.phase = phase
        self.phase_started = time.monotonic()
        self._log("PHASE_TRANSITION", source=source, destination=phase, reason=reason)

    def _publish_target(self, target):
        mode = OffboardControlMode()
        mode.timestamp = self._now_us()
        mode.position = True
        self.offboard_pub.publish(mode)
        setpoint = TrajectorySetpoint()
        setpoint.timestamp = self._now_us()
        setpoint.position = [
            float(target.north_m),
            float(target.east_m),
            float(target.down_m),
        ]
        setpoint.yaw = 0.0
        self.setpoint_pub.publish(setpoint)

    def _command(self, command, param1=0.0, param2=0.0):
        message = VehicleCommand()
        message.timestamp = self._now_us()
        message.param1 = float(param1)
        message.param2 = float(param2)
        message.command = int(command)
        message.target_system = int(self.expected_system_id)
        message.target_component = 1
        message.source_system = 250
        message.source_component = 1
        message.from_external = True
        self.command_pub.publish(message)
        key = str(int(command))
        self.command_attempts[key] = self.command_attempts.get(key, 0) + 1
        self._log(
            "VEHICLE_COMMAND_SENT",
            command=int(command),
            param1=float(param1),
            param2=float(param2),
            target_system=self.expected_system_id,
        )

    def _arm_and_offboard(self):
        self.last_arm_attempt_monotonic = time.monotonic()
        self._command(VehicleCommand.VEHICLE_CMD_DO_SET_MODE, 1.0, 6.0)
        self._command(VehicleCommand.VEHICLE_CMD_COMPONENT_ARM_DISARM, 1.0, 0.0)

    def _is_armed(self):
        return (
            self.status is not None
            and int(self.status.arming_state) == int(VehicleStatus.ARMING_STATE_ARMED)
        )

    def _tick(self):
        if self.finished:
            return
        elapsed = time.monotonic() - self.started_monotonic
        phase_elapsed = time.monotonic() - self.phase_started
        if elapsed > self.total_timeout_s:
            self._fail("total mission timeout")
            return
        if self.phase == "WAIT_TELEMETRY":
            if self.identity_verified and self.position is not None:
                self._transition("PRIME_OFFBOARD", "typed status and position received")
            return
        if self.phase == "PRIME_OFFBOARD":
            self._publish_target(self.takeoff_ned)
            self.prime_count += 1
            if self.prime_count >= 20:
                self._arm_and_offboard()
                self._transition("TAKEOFF", "20 offboard setpoints primed")
            return
        if self.phase == "TAKEOFF":
            self._publish_target(self.takeoff_ned)
            if (
                not self._is_armed()
                and time.monotonic() - self.last_arm_attempt_monotonic >= 2.0
            ):
                self._arm_and_offboard()
            if self.position and setpoint_reached(self.position, self.takeoff_ned):
                self._transition("TRANSLATE", "takeoff setpoint reached")
            elif phase_elapsed > 25:
                self._fail("takeoff setpoint timeout")
            return
        if self.phase == "TRANSLATE":
            self._publish_target(self.target_ned)
            if self.position and setpoint_reached(self.position, self.target_ned):
                self._transition("HOLD", "translation setpoint reached")
            elif phase_elapsed > 35:
                self._fail("translation setpoint timeout")
            return
        if self.phase == "HOLD":
            self._publish_target(self.target_ned)
            if phase_elapsed >= self.hold_s:
                self._command(VehicleCommand.VEHICLE_CMD_NAV_LAND)
                self._transition("LAND", "bounded hold complete")
            return
        if self.phase == "LAND":
            landed = bool(self.land and self.land.landed)
            if landed and not self._is_armed():
                self.success = True
                self.finished = True
                self._log("COMPLETE", landed=True, armed=False)
            elif phase_elapsed > 25:
                self._fail("landing timeout")

    def _fail(self, reason):
        if self.finished:
            return
        self.failure_reason = str(reason)
        if self.identity_verified and self._is_armed():
            self._command(VehicleCommand.VEHICLE_CMD_NAV_LAND)
        self.finished = True
        self.success = False
        self._log("FAIL", reason=self.failure_reason)

    def result(self):
        return {
            "vehicle_id": self.vehicle_id,
            "status": "PASS" if self.success else "FAIL",
            "final_phase": self.phase,
            "failure_reason": self.failure_reason,
            "identity_verified": self.identity_verified,
            "command_attempts": self.command_attempts,
            "target_enu": list(self.target_enu),
            "target_local_ned": list(self.target_ned),
            "final_position_ned": list(self.position) if self.position else None,
            "log": str(self.output),
            "claim_boundary": (
                "Development PX4 SITL command-path probe only; it is not physical "
                "flight, airframe calibration, mission reliability, or certification."
            ),
        }

    def close(self):
        if not self.stream.closed:
            self.stream.close()


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--vehicle-id", choices=("sentinel", "scout"), required=True)
    parser.add_argument("--home-enu", type=float, nargs=3, required=True)
    parser.add_argument("--target-enu", type=float, nargs=3, required=True)
    parser.add_argument("--takeoff-altitude-m", type=float, default=3.0)
    parser.add_argument("--hold-s", type=float, default=3.0)
    parser.add_argument("--total-timeout-s", type=float, default=100.0)
    parser.add_argument("--world-width-m", type=float, default=20.0)
    parser.add_argument("--world-length-m", type=float, default=30.0)
    parser.add_argument("--maximum-altitude-m", type=float, default=8.0)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    rclpy.init()
    node = None
    try:
        node = OffboardVehicleProbe(args)
        while rclpy.ok() and not node.finished:
            rclpy.spin_once(node, timeout_sec=0.2)
        result = node.result()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    finally:
        if node is not None:
            node.close()
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
