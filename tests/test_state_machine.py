import unittest

from drone_enhanced_core.protocol import HazardAlert, TargetBox
from drone_enhanced_core.state_machine import (
    CoordinatorState,
    SentinelCoordinator,
    TemporalFilter,
)


def make_alert(event_id="event-1", u=0.5, v=0.5):
    return HazardAlert(
        "exp-1",
        "trial-1",
        event_id,
        "sentinel",
        "fire",
        0.75,
        3,
        100,
        110,
        "a" * 64,
        TargetBox(u, v, 0.1, 0.1, 640, 480),
    )


class TemporalFilterTests(unittest.TestCase):
    def test_requires_consecutive_frames(self):
        temporal = TemporalFilter(0.6, 3)
        self.assertFalse(temporal.update(0.7))
        self.assertFalse(temporal.update(0.2))
        self.assertFalse(temporal.update(0.7))
        self.assertFalse(temporal.update(0.8))
        self.assertTrue(temporal.update(0.9))


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = SentinelCoordinator(
            timeout_ns=1000,
            rejection_cooldown_ns=5000,
            cooldown_radius=0.05,
        )

    def dispatch(self, alert=None, now_ns=100):
        alert = alert or make_alert()
        self.assertTrue(self.coordinator.begin_tracking(alert.target_box, now_ns).accepted)
        self.assertTrue(self.coordinator.dispatch_alert(alert, now_ns + 10).accepted)
        return alert

    def test_matching_confirmation_finalizes_once(self):
        alert = self.dispatch()
        result = self.coordinator.handle_verdict(
            alert.event_id, "CONFIRMED", 0.9, 500, "Scout fire detection"
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.state, CoordinatorState.CONFIRMED)
        self.assertEqual(result.final_decision.decision, "CONFIRMED")
        duplicate = self.coordinator.handle_verdict(
            alert.event_id, "CONFIRMED", 0.9, 600
        )
        self.assertFalse(duplicate.accepted)

    def test_mismatched_event_does_not_close_active_event(self):
        self.dispatch()
        result = self.coordinator.handle_verdict("other", "REJECTED", 0.1, 500)
        self.assertFalse(result.accepted)
        self.assertEqual(self.coordinator.state, CoordinatorState.AWAITING_SCOUT)

    def test_timeout_is_final_decision(self):
        alert = self.dispatch(now_ns=100)
        result = self.coordinator.check_timeout(1200)
        self.assertTrue(result.accepted)
        self.assertEqual(result.final_decision.event_id, alert.event_id)
        self.assertEqual(result.final_decision.decision, "TIMEOUT")

    def test_late_matching_verdict_becomes_timeout_not_confirmation(self):
        alert = self.dispatch(now_ns=100)
        result = self.coordinator.handle_verdict(
            alert.event_id, "CONFIRMED", 0.95, 1200, "late result"
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.final_decision.decision, "TIMEOUT")
        self.assertEqual(result.final_decision.scout_confidence, 0.0)

    def test_scout_error_is_a_terminal_non_alarm_decision(self):
        alert = self.dispatch(now_ns=100)
        result = self.coordinator.handle_verdict(
            alert.event_id, "ERROR", 0.0, 500, "stale_frame"
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.state, CoordinatorState.ERROR)
        self.assertEqual(result.final_decision.decision, "ERROR")

    def test_rejection_cooldown_expires(self):
        alert = self.dispatch(now_ns=100)
        result = self.coordinator.handle_verdict(
            alert.event_id, "REJECTED", 0.1, 500
        )
        self.assertTrue(result.accepted)
        self.coordinator.reset_after_decision()
        blocked = self.coordinator.begin_tracking(alert.target_box, 1000)
        self.assertFalse(blocked.accepted)
        allowed = self.coordinator.begin_tracking(alert.target_box, 6000)
        self.assertTrue(allowed.accepted)


if __name__ == "__main__":
    unittest.main()
