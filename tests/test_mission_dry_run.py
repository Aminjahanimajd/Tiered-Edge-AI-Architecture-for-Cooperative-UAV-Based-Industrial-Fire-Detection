import unittest

from drone_enhanced_core.mission_dry_run import (
    ActuationBlocked,
    DryRunMissionController,
    MissionMode,
    SafetyLockedFlightAdapter,
    lawnmower_search_plan,
)


class MissionDryRunTests(unittest.TestCase):
    def setUp(self):
        self.plan = lawnmower_search_plan(4.0, 6.0, 2.0, 3.0)
        self.adapter = SafetyLockedFlightAdapter()
        self.controller = DryRunMissionController(self.plan, self.adapter)

    def test_lawnmower_plan_is_deterministic_and_bounded(self):
        self.assertEqual(self.plan, lawnmower_search_plan(4.0, 6.0, 2.0, 3.0))
        self.assertEqual(len(self.plan), 3)
        self.assertEqual([point.east_m for point in self.plan], [6.0, 0.0, 6.0])
        self.assertEqual([point.north_m for point in self.plan], [0.0, 2.0, 4.0])

    def test_preview_never_transmits_or_arms(self):
        self.controller.start_search_preview()
        record = self.controller.preview_next_waypoint()
        self.assertEqual(record["kind"], "PREVIEW_ONLY")
        self.assertFalse(record["armed"])
        self.assertFalse(record["transmitted_to_vehicle"])

    def test_every_actuation_method_is_blocked(self):
        methods = [
            lambda: self.adapter.arm(),
            lambda: self.adapter.takeoff(3.0),
            lambda: self.adapter.goto(self.plan[0]),
            lambda: self.adapter.set_velocity(1.0, 0.0, 0.0),
        ]
        for method in methods:
            with self.assertRaises(ActuationBlocked):
                method()
        self.assertEqual(self.adapter.blocked_attempts, ["arm", "takeoff", "goto", "set_velocity"])

    def test_rejection_resumes_preview_but_confirmation_holds(self):
        self.controller.start_search_preview()
        self.controller.begin_verification_hold("event-1")
        self.controller.apply_verdict("event-1", "REJECTED")
        self.assertEqual(self.controller.mode, MissionMode.SEARCHING)
        self.controller.begin_verification_hold("event-2")
        self.controller.apply_verdict("event-2", "CONFIRMED")
        self.assertEqual(self.controller.mode, MissionMode.CONFIRMED_HOLD)

    def test_mismatched_verdict_cannot_change_hold(self):
        self.controller.start_search_preview()
        self.controller.begin_verification_hold("event-1")
        with self.assertRaises(ValueError):
            self.controller.apply_verdict("event-2", "CONFIRMED")
        self.assertEqual(self.controller.mode, MissionMode.HOLDING_FOR_VERIFICATION)


if __name__ == "__main__":
    unittest.main()
