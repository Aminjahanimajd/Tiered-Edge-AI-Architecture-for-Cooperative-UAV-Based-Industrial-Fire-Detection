"""ROS-independent two-vehicle mission and rejection-memory safety logic.

Simulator target positions are scenario ground truth in a local ENU frame.
They are deliberately separate from physical camera image coordinates.
"""

from __future__ import print_function

import math
from enum import Enum
from typing import NamedTuple


class MissionState(Enum):
    PREFLIGHT = "PREFLIGHT"
    TAKEOFF = "TAKEOFF"
    PATROL = "PATROL"
    SUSPECT_HOLD = "SUSPECT_HOLD"
    SCOUT_DISPATCH = "SCOUT_DISPATCH"
    VERIFYING = "VERIFYING"
    CONFIRMED_HOLD = "CONFIRMED_HOLD"
    REJECTED_RESUME = "REJECTED_RESUME"
    DEGRADED = "DEGRADED"
    RTL = "RTL"
    LANDED = "LANDED"


class LocalENU(NamedTuple):
    east_m: float
    north_m: float
    up_m: float


class ScenarioTarget(NamedTuple):
    event_id: str
    target_id: str
    position: LocalENU
    created_monotonic_ns: int
    maximum_age_ns: int


class DispatchDecision(NamedTuple):
    allowed: bool
    reason: str
    matched_event_id: object


class _RejectionEntry(NamedTuple):
    event_id: str
    target_id: str
    position: LocalENU
    rejected_confidence: float
    expires_monotonic_ns: int


def _require_identifier(name, value):
    value = str(value).strip()
    if not value:
        raise ValueError("{} cannot be empty".format(name))
    return value


def _require_position(position):
    if not isinstance(position, LocalENU):
        raise TypeError("position must be LocalENU")
    if not all(math.isfinite(float(value)) for value in position):
        raise ValueError("position components must be finite")
    return position


def _require_confidence(value):
    value = float(value)
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise ValueError("confidence must be finite and in [0, 1]")
    return value


def _distance_m(first, second):
    return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(first, second)))


class MapRejectionMemory(object):
    """Time-limited simulator-only memory of independently rejected targets."""

    def __init__(
        self,
        expiry_ns=15000000000,
        radius_m=0.5,
        override_consecutive_frames=6,
        override_confidence_increase=0.20,
    ):
        self.expiry_ns = int(expiry_ns)
        self.radius_m = float(radius_m)
        self.override_consecutive_frames = int(override_consecutive_frames)
        self.override_confidence_increase = float(override_confidence_increase)
        if self.expiry_ns < 0:
            raise ValueError("expiry_ns cannot be negative")
        if not math.isfinite(self.radius_m) or self.radius_m < 0.0:
            raise ValueError("radius_m must be finite and non-negative")
        if self.override_consecutive_frames <= 0:
            raise ValueError("override_consecutive_frames must be positive")
        if (
            not math.isfinite(self.override_confidence_increase)
            or self.override_confidence_increase < 0.0
            or self.override_confidence_increase > 1.0
        ):
            raise ValueError("override_confidence_increase must be in [0, 1]")
        self._entries = []

    def _prune(self, now_ns):
        now_ns = int(now_ns)
        self._entries = [
            entry for entry in self._entries
            if entry.expires_monotonic_ns > now_ns
        ]

    def record_rejection(self, target, confidence, now_ns):
        if not isinstance(target, ScenarioTarget):
            raise TypeError("target must be ScenarioTarget")
        _require_position(target.position)
        confidence = _require_confidence(confidence)
        now_ns = int(now_ns)
        self._prune(now_ns)
        if self.expiry_ns == 0:
            return None
        entry = _RejectionEntry(
            _require_identifier("event_id", target.event_id),
            _require_identifier("target_id", target.target_id),
            target.position,
            confidence,
            now_ns + self.expiry_ns,
        )
        self._entries.append(entry)
        return entry

    def evaluate(self, target, confidence, consecutive_frames, now_ns):
        """Return whether a new Scout dispatch is permitted.

        A different target ID is always independent, even at the same map
        position. Suppression never deletes the detection; callers must log the
        returned reason.
        """
        if not isinstance(target, ScenarioTarget):
            raise TypeError("target must be ScenarioTarget")
        _require_position(target.position)
        confidence = _require_confidence(confidence)
        consecutive_frames = int(consecutive_frames)
        now_ns = int(now_ns)
        if consecutive_frames <= 0:
            raise ValueError("consecutive_frames must be positive")
        self._prune(now_ns)
        for entry in reversed(self._entries):
            if entry.target_id != target.target_id:
                continue
            if _distance_m(entry.position, target.position) > self.radius_m:
                continue
            if consecutive_frames >= self.override_consecutive_frames:
                return DispatchDecision(
                    True, "persistent evidence overrides rejection memory", entry.event_id
                )
            if confidence - entry.rejected_confidence >= self.override_confidence_increase:
                return DispatchDecision(
                    True, "confidence increase overrides rejection memory", entry.event_id
                )
            return DispatchDecision(
                False, "target is in map-space rejection memory", entry.event_id
            )
        return DispatchDecision(True, "no active matching rejection", None)

    def active_entries(self, now_ns):
        self._prune(now_ns)
        return tuple(self._entries)


def evaluate_rejection_memory_probe_suite(
    memory, rejected_target, rejected_confidence, rejection_monotonic_ns
):
    """Evaluate the preregistered map-memory safety cases deterministically.

    The caller must already have recorded ``rejected_target`` in ``memory``.
    These are non-mutating dispatch-policy probes except that the final expiry
    check legitimately prunes the expired entry. They do not command a vehicle.
    """
    if not isinstance(memory, MapRejectionMemory):
        raise TypeError("memory must be MapRejectionMemory")
    if not isinstance(rejected_target, ScenarioTarget):
        raise TypeError("rejected_target must be ScenarioTarget")
    rejected_confidence = _require_confidence(rejected_confidence)
    rejection_monotonic_ns = int(rejection_monotonic_ns)
    if memory.expiry_ns <= 0:
        raise ValueError("formal repeated-confounder probes require positive expiry")
    if rejected_confidence > 1.0 - memory.override_confidence_increase:
        raise ValueError(
            "rejected confidence leaves no valid confidence-increase override"
        )
    if not memory.active_entries(rejection_monotonic_ns):
        raise ValueError("rejection memory has no active entry to probe")

    within_ns = rejection_monotonic_ns + min(
        max(1, memory.expiry_ns // 2), 1_000_000_000
    )
    expiry_ns = rejection_monotonic_ns + memory.expiry_ns + 1

    def candidate(suffix, target_id, position, created_ns):
        return ScenarioTarget(
            rejected_target.event_id + suffix,
            target_id,
            position,
            created_ns,
            max(memory.expiry_ns * 2, 1),
        )

    same = candidate(
        "-repeat", rejected_target.target_id, rejected_target.position, within_ns
    )
    outside = candidate(
        "-outside-radius",
        rejected_target.target_id,
        LocalENU(
            rejected_target.position.east_m + memory.radius_m + 0.01,
            rejected_target.position.north_m,
            rejected_target.position.up_m,
        ),
        within_ns,
    )
    new_target = candidate(
        "-new-target",
        rejected_target.target_id + "-new-hazard",
        rejected_target.position,
        within_ns,
    )
    expired = candidate(
        "-expired", rejected_target.target_id, rejected_target.position, expiry_ns
    )
    cases = (
        ("cooldown_suppression", same, rejected_confidence, 3, within_ns, False),
        ("outside_radius", outside, rejected_confidence, 3, within_ns, True),
        (
            "persistent_evidence_override",
            same,
            rejected_confidence,
            memory.override_consecutive_frames,
            within_ns,
            True,
        ),
        (
            "confidence_increase_override",
            same,
            min(
                1.0,
                rejected_confidence
                + memory.override_confidence_increase
                + 1e-12,
            ),
            3,
            within_ns,
            True,
        ),
        ("new_target_same_location", new_target, rejected_confidence, 3, within_ns, True),
        ("expiry_reverification", expired, rejected_confidence, 3, expiry_ns, True),
    )
    results = []
    for name, target, confidence, frames, now_ns, expected in cases:
        decision = memory.evaluate(target, confidence, frames, now_ns)
        results.append({
            "case": name,
            "event_id": target.event_id,
            "target_id": target.target_id,
            "position_enu_m": list(target.position),
            "confidence": confidence,
            "consecutive_frames": frames,
            "logical_monotonic_ns": now_ns,
            "expected_allowed": expected,
            "actual_allowed": decision.allowed,
            "reason": decision.reason,
            "matched_event_id": decision.matched_event_id,
            "passed": decision.allowed is expected,
        })
    return tuple(results)


class MissionTransition(NamedTuple):
    vehicle_id: str
    event_id: str
    simulator_time_ns: int
    monotonic_time_ns: int
    source_state: str
    destination_state: str
    reason: str


class DualVehicleMissionController(object):
    """Deterministic mission coordination core with no actuator implementation."""

    VEHICLES = ("sentinel", "scout")
    TERMINAL_VERDICTS = {"CONFIRMED", "REJECTED", "TIMEOUT", "ERROR"}

    _ALLOWED = {
        MissionState.PREFLIGHT: {
            MissionState.TAKEOFF,
            MissionState.DEGRADED,
            MissionState.LANDED,
        },
        MissionState.TAKEOFF: {
            MissionState.PATROL,
            MissionState.SCOUT_DISPATCH,
            MissionState.DEGRADED,
            MissionState.RTL,
        },
        MissionState.PATROL: {
            MissionState.SUSPECT_HOLD,
            MissionState.CONFIRMED_HOLD,
            MissionState.REJECTED_RESUME,
            MissionState.DEGRADED,
            MissionState.RTL,
        },
        MissionState.SUSPECT_HOLD: {
            MissionState.PATROL,
            MissionState.CONFIRMED_HOLD,
            MissionState.REJECTED_RESUME,
            MissionState.DEGRADED,
            MissionState.RTL,
        },
        MissionState.SCOUT_DISPATCH: {
            MissionState.VERIFYING,
            MissionState.DEGRADED,
            MissionState.RTL,
        },
        MissionState.VERIFYING: {
            MissionState.CONFIRMED_HOLD,
            MissionState.REJECTED_RESUME,
            MissionState.DEGRADED,
            MissionState.RTL,
        },
        MissionState.CONFIRMED_HOLD: {MissionState.RTL},
        MissionState.REJECTED_RESUME: {
            MissionState.PATROL,
            MissionState.PREFLIGHT,
            MissionState.RTL,
        },
        MissionState.DEGRADED: {MissionState.RTL},
        MissionState.RTL: {MissionState.LANDED},
        MissionState.LANDED: set(),
    }

    def __init__(self, rejection_memory=None):
        self.states = {
            "sentinel": MissionState.PREFLIGHT,
            "scout": MissionState.PREFLIGHT,
        }
        self.rejection_memory = rejection_memory or MapRejectionMemory()
        self.active_target = None
        self.active_confidence = None
        self.finalized_event_ids = set()
        self.transitions = []
        self.suppressed_detections = []

    def _transition(self, vehicle_id, destination, event_id, sim_ns, mono_ns, reason):
        vehicle_id = _require_identifier("vehicle_id", vehicle_id)
        if vehicle_id not in self.VEHICLES:
            raise ValueError("unknown vehicle_id: {}".format(vehicle_id))
        if not isinstance(destination, MissionState):
            raise TypeError("destination must be MissionState")
        source = self.states[vehicle_id]
        if destination not in self._ALLOWED[source]:
            raise RuntimeError(
                "illegal {} transition: {} -> {}".format(
                    vehicle_id, source.value, destination.value
                )
            )
        transition = MissionTransition(
            vehicle_id,
            str(event_id or ""),
            int(sim_ns),
            int(mono_ns),
            source.value,
            destination.value,
            str(reason),
        )
        self.states[vehicle_id] = destination
        self.transitions.append(transition)
        return transition

    def start_sentinel_patrol(self, simulator_time_ns, monotonic_time_ns):
        self.begin_sentinel_takeoff(simulator_time_ns, monotonic_time_ns)
        return self.sentinel_at_patrol(simulator_time_ns, monotonic_time_ns)

    def begin_sentinel_takeoff(self, simulator_time_ns, monotonic_time_ns):
        return self._transition(
            "sentinel", MissionState.TAKEOFF, "", simulator_time_ns,
            monotonic_time_ns, "preflight passed"
        )

    def sentinel_at_patrol(self, simulator_time_ns, monotonic_time_ns):
        self._transition(
            "sentinel", MissionState.PATROL, "", simulator_time_ns,
            monotonic_time_ns, "takeoff complete"
        )
        return self.transitions[-1]

    def report_suspect(
        self,
        target,
        confidence,
        consecutive_frames,
        simulator_time_ns,
        monotonic_time_ns,
        request_scout=True,
    ):
        if not isinstance(target, ScenarioTarget):
            raise TypeError("target must be ScenarioTarget")
        _require_identifier("event_id", target.event_id)
        _require_identifier("target_id", target.target_id)
        _require_position(target.position)
        confidence = _require_confidence(confidence)
        now_ns = int(monotonic_time_ns)
        if target.event_id in self.finalized_event_ids:
            raise ValueError("event_id was already finalized")
        if self.active_target is not None:
            raise RuntimeError("another event is active")
        if now_ns < int(target.created_monotonic_ns):
            raise ValueError("event creation time is in the future")
        if now_ns - int(target.created_monotonic_ns) > int(target.maximum_age_ns):
            raise ValueError("stale scenario target")
        if self.states["sentinel"] != MissionState.PATROL:
            raise RuntimeError("Sentinel must be in PATROL")
        decision = self.rejection_memory.evaluate(
            target, confidence, consecutive_frames, now_ns
        )
        if not decision.allowed:
            self.suppressed_detections.append(
                {
                    "event_id": target.event_id,
                    "target_id": target.target_id,
                    "monotonic_time_ns": now_ns,
                    "confidence": confidence,
                    "consecutive_frames": int(consecutive_frames),
                    "reason": decision.reason,
                    "matched_event_id": decision.matched_event_id,
                }
            )
            return decision
        self.active_target = target
        self.active_confidence = confidence
        self._transition(
            "sentinel", MissionState.SUSPECT_HOLD, target.event_id,
            simulator_time_ns, now_ns, "hazard candidate accepted"
        )
        if request_scout:
            self._transition(
                "scout", MissionState.TAKEOFF, target.event_id,
                simulator_time_ns, now_ns, "Scout dispatch requested"
            )
        return decision

    def dispatch_scout(self, event_id, simulator_time_ns, monotonic_time_ns):
        self._require_active_event(event_id)
        return self._transition(
            "scout", MissionState.SCOUT_DISPATCH, event_id,
            simulator_time_ns, monotonic_time_ns, "Scout takeoff complete"
        )

    def scout_at_standoff(self, event_id, simulator_time_ns, monotonic_time_ns):
        self._require_active_event(event_id)
        return self._transition(
            "scout", MissionState.VERIFYING, event_id,
            simulator_time_ns, monotonic_time_ns, "verification standoff reached"
        )

    def release_sentinel_after_scout_acquisition(
        self, event_id, simulator_time_ns, monotonic_time_ns
    ):
        """Resume Sentinel patrol after Scout has independently acquired the target."""
        self._require_active_event(event_id)
        if self.states["scout"] != MissionState.VERIFYING:
            raise RuntimeError("Scout must be VERIFYING before Sentinel resumes")
        return self._transition(
            "sentinel", MissionState.PATROL, event_id,
            simulator_time_ns, monotonic_time_ns,
            "Scout acquired target; Sentinel resumes independent patrol",
        )

    def _require_active_event(self, event_id):
        event_id = _require_identifier("event_id", event_id)
        if self.active_target is None or event_id != self.active_target.event_id:
            raise ValueError("event_id does not match the active event")
        return event_id

    def apply_verdict(
        self,
        event_id,
        verdict,
        scout_confidence,
        simulator_time_ns,
        monotonic_time_ns,
        defer_rejection_recovery=False,
    ):
        event_id = self._require_active_event(event_id)
        verdict = str(verdict).upper()
        if verdict not in self.TERMINAL_VERDICTS:
            raise ValueError("unsupported verdict: {}".format(verdict))
        scout_confidence = _require_confidence(scout_confidence)
        now_ns = int(monotonic_time_ns)
        target = self.active_target
        if verdict == "CONFIRMED":
            self._transition(
                "sentinel", MissionState.CONFIRMED_HOLD, event_id,
                simulator_time_ns, now_ns, "Scout confirmed hazard"
            )
            self._transition(
                "scout", MissionState.CONFIRMED_HOLD, event_id,
                simulator_time_ns, now_ns, "verification confirmed"
            )
        elif verdict == "REJECTED":
            self.rejection_memory.record_rejection(
                target, self.active_confidence, now_ns
            )
            self._transition(
                "sentinel", MissionState.REJECTED_RESUME, event_id,
                simulator_time_ns, now_ns, "Scout rejected candidate"
            )
            self._transition(
                "scout", MissionState.REJECTED_RESUME, event_id,
                simulator_time_ns, now_ns, "verification rejected"
            )
            if not defer_rejection_recovery:
                self.complete_rejection_recovery(
                    event_id, simulator_time_ns, now_ns
                )
        else:
            reason = "verification timeout" if verdict == "TIMEOUT" else "verification error"
            self._transition(
                "sentinel", MissionState.DEGRADED, event_id,
                simulator_time_ns, now_ns, reason
            )
            self._transition(
                "scout", MissionState.DEGRADED, event_id,
                simulator_time_ns, now_ns, reason
            )
        self.finalized_event_ids.add(event_id)
        self.active_target = None
        self.active_confidence = None
        return verdict

    def complete_rejection_recovery(
        self, event_id, simulator_time_ns, monotonic_time_ns
    ):
        event_id = _require_identifier("event_id", event_id)
        self._transition(
            "sentinel", MissionState.PATROL, event_id,
            simulator_time_ns, monotonic_time_ns,
            "resume at next patrol waypoint"
        )
        self._transition(
            "scout", MissionState.PREFLIGHT, event_id,
            simulator_time_ns, monotonic_time_ns,
            "return to standby complete"
        )
        return tuple(self.transitions[-2:])

    def enter_degraded(
        self, event_id, simulator_time_ns, monotonic_time_ns, reason
    ):
        """Move every nonterminal participant to DEGRADED without fabrication."""
        transitions = []
        for vehicle_id in self.VEHICLES:
            state = self.states[vehicle_id]
            if state in {MissionState.DEGRADED, MissionState.RTL, MissionState.LANDED}:
                continue
            transitions.append(
                self._transition(
                    vehicle_id,
                    MissionState.DEGRADED,
                    event_id,
                    simulator_time_ns,
                    monotonic_time_ns,
                    reason,
                )
            )
        return tuple(transitions)

    def begin_rtl(self, simulator_time_ns, monotonic_time_ns, reason):
        transitions = []
        for vehicle_id in self.VEHICLES:
            state = self.states[vehicle_id]
            if state == MissionState.LANDED:
                continue
            if state == MissionState.PREFLIGHT:
                continue
            transitions.append(
                self._transition(
                    vehicle_id, MissionState.RTL, "", simulator_time_ns,
                    monotonic_time_ns, reason
                )
            )
        return tuple(transitions)

    def mark_landed(self, vehicle_id, simulator_time_ns, monotonic_time_ns):
        return self._transition(
            vehicle_id, MissionState.LANDED, "", simulator_time_ns,
            monotonic_time_ns, "landing complete"
        )

    def transition_records(self):
        return tuple(item._asdict() for item in self.transitions)
