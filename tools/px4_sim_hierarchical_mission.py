#!/usr/bin/env python3
"""Execute one bounded hierarchical mission on two PX4 SITL vehicles only."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

import rclpy
from drone_enhanced_interfaces.msg import HazardDecision as HazardDecisionMsg
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

from drone_enhanced_core.aerial_mission import (
    DualVehicleMissionController,
    LocalENU,
    MapRejectionMemory,
    MissionState,
    ScenarioTarget,
    evaluate_rejection_memory_probe_suite,
)
from drone_enhanced_core.px4_sim_adapter import (
    EnuPosition,
    NedPosition,
    SimulationCommandGuard,
    absolute_enu_to_local_ned,
    landing_position_valid,
    setpoint_reached,
)
from drone_enhanced_core.simulation_mission_plan import load_hierarchical_plan


PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)


class VehicleRuntime:
    def __init__(self, node, vehicle_id, home):
        acknowledgement = os.environ.get("DRONE_ENHANCED_SIMULATION_ONLY", "")
        self.guard = SimulationCommandGuard(acknowledgement, vehicle_id)
        self.vehicle_id = vehicle_id
        self.home = home
        self.status = None
        self.position = None
        self.land = None
        self.identity_verified = False
        self.last_timestamp_us = 0
        self.prime_count = 0
        self.command_attempts = {}
        self.last_arm_attempt = 0.0
        self.target_enu = home
        self.target_ned = NedPosition(0.0, 0.0, 0.0)
        self.offboard_pub = node.create_publisher(
            OffboardControlMode,
            self.guard.topic("/fmu/in/offboard_control_mode"),
            PX4_QOS,
        )
        self.setpoint_pub = node.create_publisher(
            TrajectorySetpoint,
            self.guard.topic("/fmu/in/trajectory_setpoint"),
            PX4_QOS,
        )
        self.command_pub = node.create_publisher(
            VehicleCommand,
            self.guard.topic("/fmu/in/vehicle_command"),
            PX4_QOS,
        )

    @property
    def system_id(self):
        return int(self.guard.identity["system_id"])

    def set_target(self, target_enu):
        self.target_enu = target_enu
        self.target_ned = absolute_enu_to_local_ned(target_enu, self.home)

    def armed(self):
        return (
            self.status is not None
            and int(self.status.arming_state) == int(VehicleStatus.ARMING_STATE_ARMED)
        )

    def landed(self):
        return bool(self.land and self.land.landed and not self.armed())


class HierarchicalMissionNode(Node):
    """Finite two-vehicle mission with fail-closed identity and geometry checks."""

    def __init__(self, args):
        super().__init__("dual_px4_hierarchical_mission_development_probe")
        self.args = args
        self.plan = load_hierarchical_plan(args.scenario, args.event_id)
        self.configuration = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
        environment = self.configuration["environment"]
        self.minimum_east_m = float(environment["minimum_east_m"])
        self.minimum_north_m = float(environment["minimum_north_m"])
        self.width_m = float(environment["maximum_east_m"]) - self.minimum_east_m
        self.length_m = float(environment["maximum_north_m"]) - self.minimum_north_m
        self.maximum_altitude_m = float(environment["maximum_altitude_m"])
        memory = MapRejectionMemory(
            expiry_ns=int(args.rejection_ttl_s * 1_000_000_000),
            radius_m=args.rejection_radius_m,
            override_consecutive_frames=6,
            override_confidence_increase=0.20,
        )
        self.controller = DualVehicleMissionController(memory)
        self.vehicles = {
            "sentinel": VehicleRuntime(self, "sentinel", self.plan.sentinel_home),
            "scout": VehicleRuntime(self, "scout", self.plan.scout_home),
        }
        self.output = Path(args.output)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        if self.output.exists():
            raise FileExistsError(self.output)
        self.stream = self.output.open("x", encoding="utf-8", newline="\n")
        self.started_monotonic = time.monotonic()
        self.phase_started = self.started_monotonic
        self.phase = "WAIT_TELEMETRY"
        self.failure_reason = None
        self.finished = False
        self.success = False
        self.patrol_index = 0
        self.controller_log_index = 0
        self.verdict_applied = False
        self.land_commanded = set()
        self.resume_waypoint = None
        self.rtl_vehicle_ids = ()
        self.fault_triggered = False
        self.rejected_fault_inputs = []
        self.rejection_memory_probes = []
        self.restart_required = False
        self.recovery_prime_count = 0
        self.detection_monotonic_ns = 0
        self.alert_monotonic_ns = 0
        self.verdict_monotonic_ns = 0
        self.target_row = next(
            row for row in self.configuration["targets"]
            if row["event_id"] == self.plan.event_id
        )
        self.decision_pub = self.create_publisher(
            HazardDecisionMsg, "/swarm/hazard_decision", 10
        )

        if (
            args.runner_mode == "repeated_confounder"
            and (self.plan.expected_verdict != "REJECTED" or args.fault != "none")
        ):
            raise ValueError(
                "repeated_confounder mode requires a rejected scenario and no fault"
            )
        if args.recovery_only and (
            args.fault != "none" or args.runner_mode != "single_event"
        ):
            raise ValueError(
                "recovery-only mode requires fault=none and runner_mode=single_event"
            )

        for vehicle_id, runtime in self.vehicles.items():
            prefix = runtime.guard.identity["namespace"]
            self.create_subscription(
                VehicleStatus,
                prefix + "/fmu/out/vehicle_status_v1",
                lambda message, key=vehicle_id: self._status(key, message),
                PX4_QOS,
            )
            self.create_subscription(
                VehicleLocalPosition,
                prefix + "/fmu/out/vehicle_local_position_v1",
                lambda message, key=vehicle_id: self._position(key, message),
                PX4_QOS,
            )
            self.create_subscription(
                VehicleLandDetected,
                prefix + "/fmu/out/vehicle_land_detected",
                lambda message, key=vehicle_id: self._land(key, message),
                PX4_QOS,
            )
            self.create_subscription(
                VehicleCommandAck,
                prefix + "/fmu/out/vehicle_command_ack",
                lambda message, key=vehicle_id: self._ack(key, message),
                PX4_QOS,
            )
        self.timer = self.create_timer(0.1, self._tick)
        self._log(
            "MISSION_START",
            event_id=self.plan.event_id,
            target_id=self.plan.target_id,
            expected_verdict=self.plan.expected_verdict,
            safety_state="PX4 SITL only; no physical transport or interface",
            claim_boundary=self.plan.claim_boundary,
        )

    def _simulator_time_ns(self):
        return max(item.last_timestamp_us for item in self.vehicles.values()) * 1000

    def _log(self, event, **values):
        row = {
            "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "monotonic_ns": time.monotonic_ns(),
            "simulator_time_ns": self._simulator_time_ns(),
            "phase": self.phase,
            "event": event,
        }
        row.update(values)
        self.stream.write(json.dumps(row, sort_keys=True) + "\n")
        self.stream.flush()

    def _status(self, vehicle_id, message):
        runtime = self.vehicles[vehicle_id]
        try:
            runtime.guard.validate_status_identity(message.system_id)
            if not runtime.identity_verified:
                runtime.identity_verified = True
                self._log(
                    "IDENTITY_VERIFIED",
                    vehicle_id=vehicle_id,
                    system_id=int(message.system_id),
                )
            runtime.status = message
            runtime.last_timestamp_us = max(
                runtime.last_timestamp_us, int(message.timestamp)
            )
        except BaseException as exc:
            self._fail(f"{vehicle_id} identity validation failed: {exc}")

    def _position(self, vehicle_id, message):
        runtime = self.vehicles[vehicle_id]
        runtime.position = NedPosition(
            float(message.x), float(message.y), float(message.z)
        )
        runtime.last_timestamp_us = max(
            runtime.last_timestamp_us, int(message.timestamp)
        )

    def _land(self, vehicle_id, message):
        runtime = self.vehicles[vehicle_id]
        runtime.land = message
        runtime.last_timestamp_us = max(
            runtime.last_timestamp_us, int(message.timestamp)
        )

    def _ack(self, vehicle_id, message):
        runtime = self.vehicles[vehicle_id]
        runtime.last_timestamp_us = max(
            runtime.last_timestamp_us, int(message.timestamp)
        )
        self._log(
            "VEHICLE_COMMAND_ACK",
            vehicle_id=vehicle_id,
            command=int(message.command),
            result=int(message.result),
            target_system=int(message.target_system),
            target_component=int(message.target_component),
        )

    def _validate_target(self, vehicle_id, target):
        return self.vehicles[vehicle_id].guard.validate_target(
            target,
            self.width_m,
            self.length_m,
            self.maximum_altitude_m,
            minimum_east_m=self.minimum_east_m,
            minimum_north_m=self.minimum_north_m,
        )

    def _set_target(self, vehicle_id, target, purpose):
        target = self._validate_target(vehicle_id, target)
        runtime = self.vehicles[vehicle_id]
        runtime.set_target(target)
        self._log(
            "SETPOINT_SELECTED",
            vehicle_id=vehicle_id,
            purpose=purpose,
            target_enu_m=list(target),
            target_local_ned_m=list(runtime.target_ned),
        )

    def _transition(self, destination, reason):
        source = self.phase
        self.phase = destination
        self.phase_started = time.monotonic()
        self._log(
            "PHASE_TRANSITION",
            source=source,
            destination=destination,
            reason=reason,
        )

    def _publish_target(self, vehicle_id):
        runtime = self.vehicles[vehicle_id]
        mode = OffboardControlMode()
        mode.timestamp = self.get_clock().now().nanoseconds // 1000
        mode.position = True
        runtime.offboard_pub.publish(mode)
        setpoint = TrajectorySetpoint()
        setpoint.timestamp = mode.timestamp
        setpoint.position = [
            float(runtime.target_ned.north_m),
            float(runtime.target_ned.east_m),
            float(runtime.target_ned.down_m),
        ]
        setpoint.yaw = 0.0
        runtime.setpoint_pub.publish(setpoint)

    def _hold_current_position(self, vehicle_id, purpose):
        runtime = self.vehicles[vehicle_id]
        if runtime.position is None:
            raise RuntimeError("cannot hold without a local-position sample")
        current_enu = EnuPosition(
            runtime.home.east_m + runtime.position.east_m,
            runtime.home.north_m + runtime.position.north_m,
            runtime.home.up_m - runtime.position.down_m,
        )
        self._set_target(vehicle_id, current_enu, purpose)

    def _publish_hazard_decision(self, decision, reason):
        now_ns = time.monotonic_ns()
        message = HazardDecisionMsg()
        message.header.stamp = self.get_clock().now().to_msg()
        message.experiment_id = "dual-px4-visual-mission"
        message.trial_id = self.args.event_id
        message.event_id = self.plan.event_id
        message.decision = str(decision)
        message.hazard_type = str(self.target_row["hazard_type"])
        message.sentinel_confidence = float(self.args.sentinel_confidence)
        message.scout_confidence = float(self.args.scout_confidence)
        message.detection_monotonic_ns = int(self.detection_monotonic_ns)
        message.alert_sent_monotonic_ns = int(self.alert_monotonic_ns)
        message.verdict_received_monotonic_ns = int(self.verdict_monotonic_ns)
        message.decision_monotonic_ns = int(now_ns)
        message.reason = str(reason)
        self.decision_pub.publish(message)
        self._log(
            "INDUSTRIAL_ALARM_ACTION_EMITTED",
            event_id=self.plan.event_id,
            decision=str(decision),
            topic="/swarm/hazard_decision",
            interface="drone_enhanced_interfaces/msg/HazardDecision",
            evidence_boundary=(
                "scenario-defined simulated verdict; no Gazebo camera detector "
                "or physical alarm actuator"
            ),
        )

    def _command(self, vehicle_id, command, param1=0.0, param2=0.0):
        runtime = self.vehicles[vehicle_id]
        message = VehicleCommand()
        message.timestamp = self.get_clock().now().nanoseconds // 1000
        message.param1 = float(param1)
        message.param2 = float(param2)
        message.command = int(command)
        message.target_system = runtime.system_id
        message.target_component = 1
        message.source_system = 250
        message.source_component = 1
        message.from_external = True
        runtime.command_pub.publish(message)
        key = str(int(command))
        runtime.command_attempts[key] = runtime.command_attempts.get(key, 0) + 1
        self._log(
            "VEHICLE_COMMAND_SENT",
            vehicle_id=vehicle_id,
            command=int(command),
            param1=float(param1),
            param2=float(param2),
            target_system=runtime.system_id,
        )

    def _arm_offboard(self, vehicle_id):
        runtime = self.vehicles[vehicle_id]
        runtime.last_arm_attempt = time.monotonic()
        self._command(vehicle_id, VehicleCommand.VEHICLE_CMD_DO_SET_MODE, 1.0, 6.0)
        self._command(
            vehicle_id, VehicleCommand.VEHICLE_CMD_COMPONENT_ARM_DISARM, 1.0, 0.0
        )

    def _land_command(self, vehicle_id):
        if vehicle_id not in self.land_commanded:
            self._command(vehicle_id, VehicleCommand.VEHICLE_CMD_NAV_LAND)
            self.land_commanded.add(vehicle_id)

    def _reached(self, vehicle_id):
        runtime = self.vehicles[vehicle_id]
        return bool(
            runtime.position is not None
            and setpoint_reached(
                runtime.position,
                runtime.target_ned,
                self.args.horizontal_tolerance_m,
                self.args.vertical_tolerance_m,
            )
        )

    def _controller_call(self, method, *values, **keywords):
        result = method(
            *values,
            self._simulator_time_ns(),
            time.monotonic_ns(),
            **keywords,
        )
        self._flush_controller_logs()
        return result

    def _flush_controller_logs(self):
        while self.controller_log_index < len(self.controller.transitions):
            transition = self.controller.transitions[self.controller_log_index]
            self.controller_log_index += 1
            self._log("MISSION_STATE_TRANSITION", **transition._asdict())

    def _tick(self):
        if self.finished:
            return
        elapsed = time.monotonic() - self.started_monotonic
        phase_elapsed = time.monotonic() - self.phase_started
        if elapsed > self.args.total_timeout_s:
            self._fail("total hierarchical mission timeout")
            return

        if self.phase == "WAIT_TELEMETRY":
            ready = all(
                item.identity_verified and item.position is not None
                for item in self.vehicles.values()
            )
            if ready:
                if self.args.recovery_only:
                    self._begin_restart_recovery()
                    return
                altitude = self.configuration["mission"]["sentinel_patrol_altitude_m"]
                target = EnuPosition(
                    self.plan.sentinel_home.east_m,
                    self.plan.sentinel_home.north_m,
                    float(altitude),
                )
                self._set_target("sentinel", target, "TAKEOFF")
                self._controller_call(self.controller.begin_sentinel_takeoff)
                self._transition("SENTINEL_PRIME", "both vehicle identities verified")
            return

        if self.phase == "RECOVERY_PRIME":
            for vehicle_id in self.rtl_vehicle_ids:
                self._publish_target(vehicle_id)
            self.recovery_prime_count += 1
            if self.recovery_prime_count >= 20:
                for vehicle_id in self.rtl_vehicle_ids:
                    if self.vehicles[vehicle_id].armed():
                        self._command(
                            vehicle_id,
                            VehicleCommand.VEHICLE_CMD_DO_SET_MODE,
                            1.0,
                            6.0,
                        )
                self._transition(
                    "RTL_TRANSIT",
                    "replacement mission node primed safe RTL setpoints",
                )
            return

        if self.phase == "SENTINEL_PRIME":
            self._publish_target("sentinel")
            runtime = self.vehicles["sentinel"]
            runtime.prime_count += 1
            if runtime.prime_count >= 20:
                self._arm_offboard("sentinel")
                self._transition("SENTINEL_TAKEOFF", "20 setpoints primed")
            return

        if self.phase == "SENTINEL_TAKEOFF":
            self._publish_target("sentinel")
            runtime = self.vehicles["sentinel"]
            if not runtime.armed() and time.monotonic() - runtime.last_arm_attempt >= 2:
                self._arm_offboard("sentinel")
            if self._reached("sentinel"):
                self._controller_call(self.controller.sentinel_at_patrol)
                first = self.plan.sentinel_patrol[0]
                self.patrol_index = 0
                self._set_target("sentinel", first.position_enu, "PATROL")
                self._transition("SENTINEL_PATROL", "takeoff altitude reached")
            elif phase_elapsed > self.args.takeoff_timeout_s:
                self._fail("Sentinel takeoff timeout")
            return

        if self.phase == "SENTINEL_PATROL":
            self._publish_target("sentinel")
            if self._reached("sentinel"):
                if self.args.fault == "low_battery" and self.patrol_index >= 1:
                    self._enter_degraded("simulated low battery during patrol")
                    return
                if self.patrol_index >= self.plan.sentinel_hold.index:
                    now_ns = time.monotonic_ns()
                    target = ScenarioTarget(
                        self.plan.event_id,
                        self.plan.target_id,
                        LocalENU(*self.target_row["position_enu_m"]),
                        now_ns,
                        10_000_000_000,
                    )
                    decision = self.controller.report_suspect(
                        target,
                        self.args.sentinel_confidence,
                        self.args.consecutive_frames,
                        self._simulator_time_ns(),
                        now_ns,
                        request_scout=self.args.fault not in {
                            "lost_alert", "scout_unavailable",
                            "invalid_or_out_of_geofence_target",
                        },
                    )
                    self._flush_controller_logs()
                    if not decision.allowed:
                        self._fail("preregistered event was unexpectedly suppressed")
                        return
                    self.detection_monotonic_ns = now_ns
                    self.alert_monotonic_ns = time.monotonic_ns()
                    self._log(
                        "SCENARIO_HAZARD_TRIGGER",
                        event_id=self.plan.event_id,
                        target_id=self.plan.target_id,
                        hazard_type=self.target_row["hazard_type"],
                        confidence=float(self.args.sentinel_confidence),
                        consecutive_frames=int(self.args.consecutive_frames),
                        position_enu_m=self.target_row["position_enu_m"],
                        evidence_boundary=(
                            "scenario-defined trigger and local-ENU truth; not "
                            "Gazebo camera inference or vision localization"
                        ),
                    )
                    self._log(
                        "SIMULATED_TARGET_TRACKING_ACTIVE",
                        event_id=self.plan.event_id,
                        vehicle_id="sentinel",
                        tracking_basis="scenario target held at nearest patrol point",
                    )
                    self._transition(
                        "SUSPECT_HOLD", "scenario-defined hazard trigger accepted"
                    )
                else:
                    self.patrol_index += 1
                    waypoint = self.plan.sentinel_patrol[self.patrol_index]
                    self._set_target("sentinel", waypoint.position_enu, "PATROL")
            elif phase_elapsed > self.args.patrol_timeout_s:
                self._fail("Sentinel patrol waypoint timeout")
            return

        if self.phase == "SUSPECT_HOLD":
            self._publish_target("sentinel")
            if self.args.fault == "invalid_or_out_of_geofence_target":
                invalid_target = EnuPosition(
                    self.minimum_east_m + self.width_m + 1.0,
                    self.minimum_north_m,
                    1.0,
                )
                try:
                    self.vehicles["scout"].guard.validate_target(
                        invalid_target,
                        self.width_m,
                        self.length_m,
                        self.maximum_altitude_m,
                        self.minimum_east_m,
                        self.minimum_north_m,
                    )
                except ValueError as error:
                    self.fault_triggered = True
                    self.rejected_fault_inputs.append({
                        "input": "out_of_geofence_target",
                        "position_enu_m": list(invalid_target),
                        "reason": str(error),
                    })
                    self._log(
                        "FAULT_INPUT_REJECTED",
                        input="out_of_geofence_target",
                        position_enu_m=list(invalid_target),
                        reason=str(error),
                    )
                    self._enter_degraded(
                        "simulated invalid or out-of-geofence target"
                    )
                else:
                    self._fail("out-of-geofence target was accepted")
                return
            if self.args.fault in {"lost_alert", "scout_unavailable"}:
                self._enter_degraded(
                    "simulated lost alert" if self.args.fault == "lost_alert"
                    else "simulated Scout unavailable"
                )
                return
            altitude = self.configuration["mission"]["scout_transit_altitude_m"]
            target = EnuPosition(
                self.plan.scout_home.east_m,
                self.plan.scout_home.north_m,
                float(altitude),
            )
            self._set_target("scout", target, "SCOUT_TAKEOFF")
            self._transition("SCOUT_PRIME", "Sentinel holding; Scout dispatch starts")
            return

        if self.phase == "SCOUT_PRIME":
            self._publish_target("sentinel")
            self._publish_target("scout")
            runtime = self.vehicles["scout"]
            runtime.prime_count += 1
            if runtime.prime_count >= 20:
                self._arm_offboard("scout")
                self._transition("SCOUT_TAKEOFF", "20 Scout setpoints primed")
            return

        if self.phase == "SCOUT_TAKEOFF":
            self._publish_target("sentinel")
            self._publish_target("scout")
            runtime = self.vehicles["scout"]
            if not runtime.armed() and time.monotonic() - runtime.last_arm_attempt >= 2:
                self._arm_offboard("scout")
            if self._reached("scout"):
                self._controller_call(
                    self.controller.dispatch_scout, self.plan.event_id
                )
                self._set_target(
                    "scout", self.plan.scout_standoff.position_enu, "SCOUT_DISPATCH"
                )
                self._transition("SCOUT_TRANSIT", "Scout takeoff complete")
            elif phase_elapsed > self.args.takeoff_timeout_s:
                self._fail("Scout takeoff timeout")
            return

        if self.phase == "SCOUT_TRANSIT":
            self._publish_target("sentinel")
            self._publish_target("scout")
            if self._reached("scout"):
                self._controller_call(
                    self.controller.scout_at_standoff, self.plan.event_id
                )
                self._log(
                    "SCOUT_TARGET_ACQUIRED",
                    event_id=self.plan.event_id,
                    vehicle_id="scout",
                    acquisition_basis=(
                        "arrival at the scenario-defined safe standoff point; "
                        "not camera-derived target localization"
                    ),
                )
                self._controller_call(
                    self.controller.release_sentinel_after_scout_acquisition,
                    self.plan.event_id,
                )
                self._log(
                    "SIMULATED_TARGET_TRACKING_RELEASED",
                    event_id=self.plan.event_id,
                    vehicle_id="sentinel",
                    reason="Scout acquired the scenario target",
                )
                next_index = min(
                    self.patrol_index + 1, len(self.plan.sentinel_patrol) - 1
                )
                self.patrol_index = next_index
                self._set_target(
                    "sentinel",
                    self.plan.sentinel_patrol[next_index].position_enu,
                    "PATROL_RESUME_DURING_SCOUT_VERIFICATION",
                )
                self._transition(
                    "VERIFYING",
                    "Scout acquired target; Sentinel resumed independent patrol",
                )
            elif phase_elapsed > self.args.transit_timeout_s:
                self._fail("Scout standoff transit timeout")
            return

        if self.phase == "VERIFYING":
            self._publish_target("sentinel")
            self._publish_target("scout")
            if self.args.fault == "mission_node_restart":
                self.fault_triggered = True
                self.restart_required = True
                self.finished = True
                self._log(
                    "MISSION_NODE_RESTART_REQUIRED",
                    event_id=self.plan.event_id,
                    reason=(
                        "injected coordinator process termination at VERIFYING; "
                        "replacement process must reacquire identities and land"
                    ),
                )
                return
            if phase_elapsed >= self.args.verification_hold_s:
                if self.args.fault in {
                    "delayed_verdict", "sensor_or_inference_error"
                }:
                    verdict = (
                        "TIMEOUT" if self.args.fault == "delayed_verdict"
                        else "ERROR"
                    )
                    self.controller.apply_verdict(
                        self.plan.event_id,
                        verdict,
                        0.0,
                        self._simulator_time_ns(),
                        time.monotonic_ns(),
                    )
                    self._flush_controller_logs()
                    self.fault_triggered = True
                    self._log(
                        "UNVERIFIED_HAZARD_RECORD",
                        event_id=self.plan.event_id,
                        injected_fault=self.args.fault,
                        reason=f"verification terminated with {verdict}",
                    )
                    self._begin_rtl(f"safe response to {self.args.fault}")
                    return
                if self.args.fault == "duplicate_or_stale_verdict":
                    stale_event = self.plan.event_id + "-stale"
                    try:
                        self.controller.apply_verdict(
                            stale_event,
                            self.plan.expected_verdict,
                            self.args.scout_confidence,
                            self._simulator_time_ns(),
                            time.monotonic_ns(),
                        )
                    except ValueError as error:
                        self.rejected_fault_inputs.append({
                            "input": "stale_verdict",
                            "event_id": stale_event,
                            "reason": str(error),
                        })
                        self._log(
                            "FAULT_INPUT_REJECTED",
                            input="stale_verdict",
                            event_id=stale_event,
                            reason=str(error),
                        )
                    else:
                        self._fail("stale verdict was accepted")
                        return
                self.controller.apply_verdict(
                    self.plan.event_id,
                    self.plan.expected_verdict,
                    self.args.scout_confidence,
                    self._simulator_time_ns(),
                    time.monotonic_ns(),
                    defer_rejection_recovery=(
                        self.plan.expected_verdict == "REJECTED"
                    ),
                )
                self._flush_controller_logs()
                self.verdict_monotonic_ns = time.monotonic_ns()
                self._log(
                    "SCENARIO_VERDICT_APPLIED",
                    event_id=self.plan.event_id,
                    verdict=self.plan.expected_verdict,
                    scout_confidence=float(self.args.scout_confidence),
                    evidence_boundary=(
                        "scenario-defined verification result; not Gazebo camera "
                        "model inference"
                    ),
                )
                if self.args.runner_mode == "repeated_confounder":
                    rejected_row = next(
                        row for row in self.configuration["targets"]
                        if row["event_id"] == self.plan.event_id
                    )
                    rejected_target = ScenarioTarget(
                        self.plan.event_id,
                        self.plan.target_id,
                        LocalENU(*rejected_row["position_enu_m"]),
                        time.monotonic_ns(),
                        10_000_000_000,
                    )
                    active = self.controller.rejection_memory.active_entries(
                        time.monotonic_ns()
                    )
                    if not active:
                        self._fail("rejection memory entry missing after Scout rejection")
                        return
                    rejection_ns = active[-1].expires_monotonic_ns - (
                        int(self.args.rejection_ttl_s * 1_000_000_000)
                    )
                    self.rejection_memory_probes = list(
                        evaluate_rejection_memory_probe_suite(
                            self.controller.rejection_memory,
                            rejected_target,
                            self.args.sentinel_confidence,
                            rejection_ns,
                        )
                    )
                    for probe in self.rejection_memory_probes:
                        self._log(
                            "REJECTION_MEMORY_PROBE",
                            time_basis=(
                                "deterministic logical monotonic offsets; policy "
                                "evaluation only; no second vehicle dispatch"
                            ),
                            **probe,
                        )
                    if not all(row["passed"] for row in self.rejection_memory_probes):
                        self._fail("rejection-memory probe suite failed")
                        return
                self.verdict_applied = True
                if self.args.fault == "duplicate_or_stale_verdict":
                    try:
                        self.controller.apply_verdict(
                            self.plan.event_id,
                            self.plan.expected_verdict,
                            self.args.scout_confidence,
                            self._simulator_time_ns(),
                            time.monotonic_ns(),
                        )
                    except ValueError as error:
                        self.rejected_fault_inputs.append({
                            "input": "duplicate_verdict",
                            "event_id": self.plan.event_id,
                            "reason": str(error),
                        })
                        self._log(
                            "FAULT_INPUT_REJECTED",
                            input="duplicate_verdict",
                            event_id=self.plan.event_id,
                            reason=str(error),
                        )
                    else:
                        self._fail("duplicate verdict was accepted")
                        return
                    self.fault_triggered = len(self.rejected_fault_inputs) == 2
                if self.plan.expected_verdict == "CONFIRMED":
                    # Keep the last validated Sentinel patrol and Scout standoff
                    # setpoints. Reconstructing an absolute target from a live
                    # estimator sample can briefly exceed the scenario fence
                    # during simulator transients and is unnecessary here.
                    self._publish_hazard_decision(
                        "CONFIRMED",
                        "Scout confirmed scenario-defined fire candidate",
                    )
                    self._transition("CONFIRMED_HOLD", "Scout confirmed hazard")
                else:
                    next_index = min(
                        self.patrol_index + 1, len(self.plan.sentinel_patrol) - 1
                    )
                    self.resume_waypoint = self.plan.sentinel_patrol[next_index]
                    self._set_target(
                        "sentinel", self.resume_waypoint.position_enu,
                        "REJECTED_RESUME",
                    )
                    self._set_target(
                        "scout", self.plan.scout_rtl.position_enu,
                        "RETURN_STANDBY",
                    )
                    self._transition("REJECTION_RECOVERY", "Scout rejected candidate")
            return

        if self.phase == "CONFIRMED_HOLD":
            self._publish_target("sentinel")
            self._publish_target("scout")
            if phase_elapsed >= self.args.confirmed_hold_s:
                self._begin_rtl("bounded confirmed-hazard hold complete")
            return

        if self.phase == "REJECTION_RECOVERY":
            self._publish_target("sentinel")
            self._publish_target("scout")
            if self._reached("sentinel") and self._reached("scout"):
                self._land_command("scout")
                self._transition(
                    "REJECTION_SCOUT_LAND",
                    "Sentinel reached next waypoint; Scout reached standby home",
                )
            elif phase_elapsed > self.args.transit_timeout_s:
                self._fail("rejection recovery timeout")
            return

        if self.phase == "REJECTION_SCOUT_LAND":
            self._publish_target("sentinel")
            if self.vehicles["scout"].landed():
                self._controller_call(
                    self.controller.complete_rejection_recovery,
                    self.plan.event_id,
                )
                self._controller_call(self.controller.mark_landed, "scout")
                self._begin_rtl("development rejection-resume action complete")
            elif phase_elapsed > self.args.landing_timeout_s:
                self._fail("Scout standby landing timeout")
            return

        if self.phase == "RTL_TRANSIT":
            for vehicle_id in self.rtl_vehicle_ids:
                self._publish_target(vehicle_id)
            if all(self._reached(vehicle_id) for vehicle_id in self.rtl_vehicle_ids):
                self._transition(
                    "RTL_HOLD", "all active vehicles reached RTL points"
                )
            elif phase_elapsed > self.args.transit_timeout_s:
                self._fail("RTL transit timeout")
            return

        if self.phase == "RTL_HOLD":
            for vehicle_id in self.rtl_vehicle_ids:
                self._publish_target(vehicle_id)
            if phase_elapsed >= self.args.rtl_hold_s:
                for vehicle_id in self.rtl_vehicle_ids:
                    self._land_command(vehicle_id)
                self._transition(
                    "LANDING", "bounded home-position stabilization complete"
                )
            return

        if self.phase == "LANDING":
            if all(runtime.landed() for runtime in self.vehicles.values()):
                for vehicle_id in self.vehicles:
                    if self.controller.states[vehicle_id] != MissionState.LANDED:
                        self._controller_call(
                            self.controller.mark_landed, vehicle_id
                        )
                violations = {
                    vehicle_id: (
                        list(runtime.position) if runtime.position is not None
                        else None
                    )
                    for vehicle_id, runtime in self.vehicles.items()
                    if runtime.position is None
                    or not landing_position_valid(
                        runtime.position,
                        self.args.maximum_touchdown_horizontal_error_m,
                        self.args.maximum_touchdown_vertical_error_m,
                    )
                }
                if violations:
                    self.failure_reason = "touchdown position exceeds home tolerance"
                    self.finished = True
                    self.success = False
                    self._log(
                        "MISSION_FAIL",
                        reason=self.failure_reason,
                        touchdown_violations_ned_m=violations,
                    )
                else:
                    self.success = True
                    self.finished = True
                    self._log("MISSION_COMPLETE", landed=True, armed=False)
            elif phase_elapsed > self.args.landing_timeout_s:
                self._fail("landing timeout")

    def _begin_rtl(self, reason):
        self.controller.begin_rtl(
            self._simulator_time_ns(), time.monotonic_ns(), reason
        )
        self._flush_controller_logs()
        for vehicle_id, runtime in self.vehicles.items():
            if (
                self.controller.states[vehicle_id] == MissionState.RTL
                and runtime.landed()
            ):
                self._controller_call(
                    self.controller.mark_landed, vehicle_id
                )
        self.rtl_vehicle_ids = tuple(
            vehicle_id for vehicle_id in self.vehicles
            if self.controller.states[vehicle_id] == MissionState.RTL
        )
        if not self.rtl_vehicle_ids:
            self._fail("RTL requested without an active vehicle")
            return
        if "sentinel" in self.rtl_vehicle_ids:
            self._set_target("sentinel", self.plan.sentinel_rtl.position_enu, "RTL")
        if "scout" in self.rtl_vehicle_ids:
            self._set_target("scout", self.plan.scout_rtl.position_enu, "RTL")
        self._transition("RTL_TRANSIT", reason)

    def _begin_restart_recovery(self):
        """Fail closed after a real coordinator-process replacement."""
        reason = "replacement mission node entered fail-safe recovery"
        self.controller.enter_degraded(
            self.plan.event_id,
            self._simulator_time_ns(),
            time.monotonic_ns(),
            reason,
        )
        self._flush_controller_logs()
        self.controller.begin_rtl(
            self._simulator_time_ns(), time.monotonic_ns(), reason
        )
        self._flush_controller_logs()
        for vehicle_id, runtime in self.vehicles.items():
            if runtime.landed():
                self._controller_call(self.controller.mark_landed, vehicle_id)
        self.rtl_vehicle_ids = tuple(
            vehicle_id for vehicle_id in self.vehicles
            if self.controller.states[vehicle_id] == MissionState.RTL
        )
        if not self.rtl_vehicle_ids:
            self.success = True
            self.finished = True
            self._log(
                "MISSION_COMPLETE",
                landed=True,
                armed=False,
                reason="replacement found both vehicles already landed",
            )
            return
        if "sentinel" in self.rtl_vehicle_ids:
            self._set_target("sentinel", self.plan.sentinel_rtl.position_enu, "RTL")
        if "scout" in self.rtl_vehicle_ids:
            self._set_target("scout", self.plan.scout_rtl.position_enu, "RTL")
        self._transition(
            "RECOVERY_PRIME",
            "replacement reacquired both identities and selected safe RTL targets",
        )

    def _enter_degraded(self, reason):
        self.fault_triggered = True
        self.controller.enter_degraded(
            self.plan.event_id,
            self._simulator_time_ns(),
            time.monotonic_ns(),
            reason,
        )
        self._flush_controller_logs()
        self._log(
            "UNVERIFIED_HAZARD_RECORD",
            event_id=self.plan.event_id,
            injected_fault=self.args.fault,
            reason=reason,
        )
        self._begin_rtl(f"safe response to {self.args.fault}")

    def _fail(self, reason):
        if self.finished:
            return
        self.failure_reason = str(reason)
        for vehicle_id, runtime in self.vehicles.items():
            if runtime.identity_verified and runtime.armed():
                self._land_command(vehicle_id)
        self.finished = True
        self.success = False
        self._log("MISSION_FAIL", reason=self.failure_reason)

    def result(self):
        return {
            "status": (
                "RESTART_REQUIRED"
                if self.restart_required
                else ("PASS" if self.success else "FAIL")
            ),
            "event_id": self.plan.event_id,
            "target_id": self.plan.target_id,
            "expected_verdict": self.plan.expected_verdict,
            "injected_fault": self.args.fault,
            "fault_triggered": self.fault_triggered,
            "rejected_fault_inputs": self.rejected_fault_inputs,
            "runner_mode": self.args.runner_mode,
            "rejection_memory_probes": self.rejection_memory_probes,
            "recovery_only": self.args.recovery_only,
            "restart_required": self.restart_required,
            "final_phase": self.phase,
            "failure_reason": self.failure_reason,
            "mission_states": {
                key: value.value for key, value in self.controller.states.items()
            },
            "transition_count": len(self.controller.transitions),
            "vehicles": {
                key: {
                    "system_id": runtime.system_id,
                    "identity_verified": runtime.identity_verified,
                    "command_attempts": runtime.command_attempts,
                    "landed": runtime.landed(),
                    "final_position_ned_m": (
                        list(runtime.position) if runtime.position else None
                    ),
                }
                for key, runtime in self.vehicles.items()
            },
            "claim_boundary": (
                "One development mission on provisional PX4/Gazebo proxies; "
                "not physical flight, formal reliability, industrial deployment, "
                "or vision-derived localization evidence."
            ),
        }

    def close(self):
        if not self.stream.closed:
            self.stream.close()


def parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--total-timeout-s", type=float, default=360.0)
    parser.add_argument("--takeoff-timeout-s", type=float, default=30.0)
    parser.add_argument("--patrol-timeout-s", type=float, default=180.0)
    parser.add_argument("--transit-timeout-s", type=float, default=75.0)
    parser.add_argument("--landing-timeout-s", type=float, default=30.0)
    parser.add_argument("--verification-hold-s", type=float, default=3.0)
    parser.add_argument("--confirmed-hold-s", type=float, default=5.0)
    parser.add_argument("--rtl-hold-s", type=float, default=3.0)
    parser.add_argument("--horizontal-tolerance-m", type=float, default=0.6)
    parser.add_argument("--vertical-tolerance-m", type=float, default=0.4)
    parser.add_argument(
        "--maximum-touchdown-horizontal-error-m", type=float, default=2.0
    )
    parser.add_argument(
        "--maximum-touchdown-vertical-error-m", type=float, default=0.5
    )
    parser.add_argument("--sentinel-confidence", type=float, default=0.72)
    parser.add_argument("--scout-confidence", type=float, default=0.91)
    parser.add_argument("--consecutive-frames", type=int, default=3)
    parser.add_argument("--rejection-ttl-s", type=float, default=15.0)
    parser.add_argument("--rejection-radius-m", type=float, default=0.5)
    parser.add_argument(
        "--runner-mode",
        choices=("single_event", "repeated_confounder"),
        default="single_event",
    )
    parser.add_argument("--recovery-only", action="store_true")
    parser.add_argument(
        "--fault",
        choices=(
            "none",
            "lost_alert",
            "delayed_verdict",
            "scout_unavailable",
            "low_battery",
            "sensor_or_inference_error",
            "duplicate_or_stale_verdict",
            "invalid_or_out_of_geofence_target",
            "mission_node_restart",
        ),
        default="none",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    rclpy.init()
    node = None
    try:
        node = HierarchicalMissionNode(args)
        while rclpy.ok() and not node.finished:
            rclpy.spin_once(node, timeout_sec=0.2)
        result = node.result()
        print(json.dumps(result, indent=2, sort_keys=True))
        if result["status"] == "PASS":
            return 0
        if result["status"] == "RESTART_REQUIRED":
            return 75
        return 1
    finally:
        if node is not None:
            node.close()
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
