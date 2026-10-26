"""Deterministic Sentinel temporal filtering and coordination state logic."""

from __future__ import print_function

import math
from enum import Enum
from typing import NamedTuple

from .protocol import HazardAlert, TargetBox


class CoordinatorState(Enum):
    SEARCHING = "SEARCHING"
    TRACKING = "TRACKING"
    AWAITING_SCOUT = "AWAITING_SCOUT"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


class FinalDecision(NamedTuple):
    event_id: str
    decision: str
    decision_monotonic_ns: int
    sentinel_confidence: float
    scout_confidence: float
    reason: str


class TransitionResult(NamedTuple):
    accepted: bool
    state: CoordinatorState
    reason: str
    final_decision: object


class TemporalFilter(object):
    """Require a configured number of consecutive above-threshold frames."""

    def __init__(self, threshold, required_consecutive):
        self.threshold = float(threshold)
        self.required_consecutive = int(required_consecutive)
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("threshold must be in [0, 1]")
        if self.required_consecutive <= 0:
            raise ValueError("required_consecutive must be positive")
        self.count = 0
        self.triggered = False

    def update(self, confidence):
        confidence = float(confidence)
        if not math.isfinite(confidence):
            raise ValueError("confidence must be finite")
        if self.triggered:
            return True
        if confidence >= self.threshold:
            self.count += 1
        else:
            self.count = 0
        if self.count >= self.required_consecutive:
            self.triggered = True
        return self.triggered

    def reset(self):
        self.count = 0
        self.triggered = False


class _CooldownEntry(NamedTuple):
    center_u: float
    center_v: float
    expires_ns: int
    source_event_id: str


class SentinelCoordinator(object):
    """Correlate one Sentinel alert with exactly one final Scout outcome."""

    VALID_VERDICTS = {"CONFIRMED", "REJECTED", "ERROR"}

    def __init__(self, timeout_ns, rejection_cooldown_ns, cooldown_radius):
        self.timeout_ns = int(timeout_ns)
        self.rejection_cooldown_ns = int(rejection_cooldown_ns)
        self.cooldown_radius = float(cooldown_radius)
        if self.timeout_ns <= 0:
            raise ValueError("timeout_ns must be positive")
        if self.rejection_cooldown_ns < 0:
            raise ValueError("rejection_cooldown_ns cannot be negative")
        if self.cooldown_radius < 0.0 or self.cooldown_radius > 1.0:
            raise ValueError("cooldown_radius must be in [0, 1]")

        self.state = CoordinatorState.SEARCHING
        self.active_alert = None
        self.deadline_ns = None
        self._cooldowns = []
        self._finalized_event_ids = set()

    def _prune_cooldowns(self, now_ns):
        self._cooldowns = [
            entry for entry in self._cooldowns if entry.expires_ns > now_ns
        ]

    def target_is_cooling_down(self, target_box, now_ns):
        if not isinstance(target_box, TargetBox):
            raise TypeError("target_box must be a TargetBox")
        now_ns = int(now_ns)
        self._prune_cooldowns(now_ns)
        radius_squared = self.cooldown_radius * self.cooldown_radius
        for entry in self._cooldowns:
            du = target_box.center_u - entry.center_u
            dv = target_box.center_v - entry.center_v
            if du * du + dv * dv <= radius_squared:
                return True
        return False

    def begin_tracking(self, target_box, now_ns):
        if self.state != CoordinatorState.SEARCHING:
            return TransitionResult(False, self.state, "coordinator is busy", None)
        if self.target_is_cooling_down(target_box, now_ns):
            return TransitionResult(False, self.state, "target is in rejection cooldown", None)
        self.state = CoordinatorState.TRACKING
        return TransitionResult(True, self.state, "tracking started", None)

    def dispatch_alert(self, alert, now_ns):
        if not isinstance(alert, HazardAlert):
            raise TypeError("alert must be a HazardAlert")
        now_ns = int(now_ns)
        if self.state != CoordinatorState.TRACKING:
            return TransitionResult(False, self.state, "not in TRACKING state", None)
        if alert.event_id in self._finalized_event_ids:
            return TransitionResult(False, self.state, "event ID was already finalized", None)
        if self.target_is_cooling_down(alert.target_box, now_ns):
            self.state = CoordinatorState.SEARCHING
            return TransitionResult(False, self.state, "target is in rejection cooldown", None)
        self.active_alert = alert
        self.deadline_ns = now_ns + self.timeout_ns
        self.state = CoordinatorState.AWAITING_SCOUT
        return TransitionResult(True, self.state, "alert dispatched", None)

    def handle_verdict(self, event_id, verdict, scout_confidence, now_ns, reason=""):
        event_id = str(event_id)
        verdict = str(verdict).upper()
        now_ns = int(now_ns)
        scout_confidence = float(scout_confidence)
        if verdict not in self.VALID_VERDICTS:
            raise ValueError("unsupported verdict: {}".format(verdict))
        if not 0.0 <= scout_confidence <= 1.0:
            raise ValueError("scout_confidence must be in [0, 1]")
        if event_id in self._finalized_event_ids:
            return TransitionResult(False, self.state, "duplicate finalized verdict", None)
        if self.state != CoordinatorState.AWAITING_SCOUT or self.active_alert is None:
            return TransitionResult(False, self.state, "no event awaiting Scout", None)
        if event_id != self.active_alert.event_id:
            return TransitionResult(False, self.state, "verdict event ID mismatch", None)
        if now_ns > self.deadline_ns:
            return self._finalize("TIMEOUT", 0.0, now_ns, "Scout verdict arrived after deadline")
        return self._finalize(verdict, scout_confidence, now_ns, reason)

    def check_timeout(self, now_ns):
        now_ns = int(now_ns)
        if self.state != CoordinatorState.AWAITING_SCOUT or self.active_alert is None:
            return TransitionResult(False, self.state, "no event awaiting Scout", None)
        if now_ns <= self.deadline_ns:
            return TransitionResult(False, self.state, "deadline not reached", None)
        return self._finalize("TIMEOUT", 0.0, now_ns, "Scout response timeout")

    def _finalize(self, decision, scout_confidence, now_ns, reason):
        alert = self.active_alert
        if decision == "CONFIRMED":
            self.state = CoordinatorState.CONFIRMED
        elif decision == "REJECTED":
            self.state = CoordinatorState.REJECTED
            if self.rejection_cooldown_ns > 0:
                self._cooldowns.append(
                    _CooldownEntry(
                        alert.target_box.center_u,
                        alert.target_box.center_v,
                        now_ns + self.rejection_cooldown_ns,
                        alert.event_id,
                    )
                )
        elif decision == "TIMEOUT":
            self.state = CoordinatorState.TIMEOUT
        else:
            self.state = CoordinatorState.ERROR

        final = FinalDecision(
            alert.event_id,
            decision,
            now_ns,
            alert.confidence,
            scout_confidence,
            str(reason),
        )
        self._finalized_event_ids.add(alert.event_id)
        self.active_alert = None
        self.deadline_ns = None
        return TransitionResult(True, self.state, "event finalized", final)

    def reset_after_decision(self):
        if self.state in (
            CoordinatorState.CONFIRMED,
            CoordinatorState.REJECTED,
            CoordinatorState.TIMEOUT,
            CoordinatorState.ERROR,
        ):
            self.state = CoordinatorState.SEARCHING
            return TransitionResult(True, self.state, "search resumed", None)
        return TransitionResult(False, self.state, "no final decision to reset", None)
