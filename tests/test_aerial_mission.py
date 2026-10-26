import unittest

from drone_enhanced_core.aerial_mission import (
    DualVehicleMissionController,
    LocalENU,
    MapRejectionMemory,
    MissionState,
    ScenarioTarget,
    evaluate_rejection_memory_probe_suite,
)


def target(event_id="event-1", target_id="tank-a", east=5.0, created=100):
    return ScenarioTarget(
        event_id, target_id, LocalENU(east, 3.0, 0.0), created, 100000
    )


class MapRejectionMemoryTests(unittest.TestCase):
    def setUp(self):
        self.memory = MapRejectionMemory(
            expiry_ns=1000,
            radius_m=1.5,
            override_consecutive_frames=6,
            override_confidence_increase=0.20,
        )
        self.memory.record_rejection(target(), 0.60, 200)

    def test_matching_target_is_temporarily_suppressed(self):
        result = self.memory.evaluate(target("event-2"), 0.70, 3, 500)
        self.assertFalse(result.allowed)
        self.assertEqual(result.matched_event_id, "event-1")

    def test_different_target_id_is_never_suppressed(self):
        result = self.memory.evaluate(
            target("event-2", target_id="new-fire"), 0.70, 3, 500
        )
        self.assertTrue(result.allowed)

    def test_location_outside_radius_is_not_suppressed(self):
        result = self.memory.evaluate(target("event-2", east=7.0), 0.70, 3, 500)
        self.assertTrue(result.allowed)

    def test_persistence_overrides_suppression(self):
        result = self.memory.evaluate(target("event-2"), 0.70, 6, 500)
        self.assertTrue(result.allowed)
        self.assertIn("persistent", result.reason)

    def test_confidence_increase_overrides_suppression(self):
        result = self.memory.evaluate(target("event-2"), 0.81, 3, 500)
        self.assertTrue(result.allowed)
        self.assertIn("confidence", result.reason)

    def test_expiry_allows_reverification(self):
        result = self.memory.evaluate(target("event-2"), 0.61, 3, 1201)
        self.assertTrue(result.allowed)
        self.assertEqual(self.memory.active_entries(1201), ())

    def test_formal_probe_suite_covers_suppression_overrides_and_expiry(self):
        results = evaluate_rejection_memory_probe_suite(
            self.memory, target(), 0.60, 200
        )
        self.assertEqual(len(results), 6)
        self.assertTrue(all(row["passed"] for row in results))
        by_name = {row["case"]: row for row in results}
        self.assertFalse(by_name["cooldown_suppression"]["actual_allowed"])
        self.assertTrue(by_name["new_target_same_location"]["actual_allowed"])
        self.assertTrue(by_name["expiry_reverification"]["actual_allowed"])

    def test_formal_probe_suite_requires_an_active_rejection(self):
        empty = MapRejectionMemory(expiry_ns=1000, radius_m=1.5)
        with self.assertRaisesRegex(ValueError, "no active entry"):
            evaluate_rejection_memory_probe_suite(empty, target(), 0.60, 200)


class DualVehicleMissionControllerTests(unittest.TestCase):
    def setUp(self):
        self.controller = DualVehicleMissionController(
            MapRejectionMemory(expiry_ns=1000, radius_m=1.5)
        )
        self.controller.start_sentinel_patrol(10, 100)

    def dispatch(self, item=None):
        item = item or target()
        result = self.controller.report_suspect(item, 0.70, 3, 20, 200)
        self.assertTrue(result.allowed)
        self.controller.dispatch_scout(item.event_id, 30, 300)
        self.controller.scout_at_standoff(item.event_id, 40, 400)
        return item

    def test_confirmed_mission_holds_both_vehicles(self):
        item = self.dispatch()
        self.controller.apply_verdict(item.event_id, "CONFIRMED", 0.90, 50, 500)
        self.assertEqual(
            self.controller.states["sentinel"], MissionState.CONFIRMED_HOLD
        )
        self.assertEqual(
            self.controller.states["scout"], MissionState.CONFIRMED_HOLD
        )

    def test_sentinel_resumes_after_scout_acquires_then_accepts_verdict(self):
        item = self.dispatch()
        transition = self.controller.release_sentinel_after_scout_acquisition(
            item.event_id, 45, 450
        )
        self.assertEqual(transition.source_state, "SUSPECT_HOLD")
        self.assertEqual(transition.destination_state, "PATROL")
        self.controller.apply_verdict(item.event_id, "CONFIRMED", 0.90, 50, 500)
        self.assertEqual(
            self.controller.states["sentinel"], MissionState.CONFIRMED_HOLD
        )

    def test_sentinel_cannot_resume_before_scout_acquisition(self):
        item = target()
        self.controller.report_suspect(item, 0.70, 3, 20, 200)
        with self.assertRaisesRegex(RuntimeError, "Scout must be VERIFYING"):
            self.controller.release_sentinel_after_scout_acquisition(
                item.event_id, 25, 250
            )

    def test_rejection_resumes_and_suppresses_immediate_repeat(self):
        item = self.dispatch()
        self.controller.apply_verdict(item.event_id, "REJECTED", 0.10, 50, 500)
        self.assertEqual(self.controller.states["sentinel"], MissionState.PATROL)
        self.assertEqual(self.controller.states["scout"], MissionState.PREFLIGHT)
        repeated = target("event-2", created=510)
        decision = self.controller.report_suspect(repeated, 0.71, 3, 60, 600)
        self.assertFalse(decision.allowed)
        self.assertEqual(len(self.controller.suppressed_detections), 1)

    def test_rejection_recovery_can_wait_for_px4_actions(self):
        item = self.dispatch()
        self.controller.apply_verdict(
            item.event_id, "REJECTED", 0.10, 50, 500,
            defer_rejection_recovery=True,
        )
        self.assertEqual(
            self.controller.states["sentinel"], MissionState.REJECTED_RESUME
        )
        self.assertEqual(
            self.controller.states["scout"], MissionState.REJECTED_RESUME
        )
        self.controller.complete_rejection_recovery(item.event_id, 60, 600)
        self.assertEqual(self.controller.states["sentinel"], MissionState.PATROL)
        self.assertEqual(self.controller.states["scout"], MissionState.PREFLIGHT)

    def test_takeoff_and_patrol_can_follow_physical_completion(self):
        controller = DualVehicleMissionController()
        controller.begin_sentinel_takeoff(10, 100)
        self.assertEqual(controller.states["sentinel"], MissionState.TAKEOFF)
        controller.sentinel_at_patrol(20, 200)
        self.assertEqual(controller.states["sentinel"], MissionState.PATROL)

    def test_preflight_vehicle_can_be_recorded_as_landed(self):
        controller = DualVehicleMissionController()
        controller.mark_landed("scout", 10, 100)
        self.assertEqual(controller.states["scout"], MissionState.LANDED)

    def test_fault_before_scout_takeoff_degrades_both_participants(self):
        controller = DualVehicleMissionController()
        controller.start_sentinel_patrol(10, 100)
        transitions = controller.enter_degraded(
            "fault-low-battery", 20, 200, "simulated low battery"
        )
        self.assertEqual(len(transitions), 2)
        self.assertEqual(controller.states["sentinel"], MissionState.DEGRADED)
        self.assertEqual(controller.states["scout"], MissionState.DEGRADED)
        controller.begin_rtl(30, 300, "safe return")
        controller.mark_landed("sentinel", 40, 400)
        controller.mark_landed("scout", 40, 400)
        self.assertEqual(controller.states["sentinel"], MissionState.LANDED)
        self.assertEqual(controller.states["scout"], MissionState.LANDED)

    def test_new_hazard_same_location_is_not_suppressed(self):
        item = self.dispatch()
        self.controller.apply_verdict(item.event_id, "REJECTED", 0.10, 50, 500)
        new_hazard = target("event-2", target_id="fire-new", created=510)
        decision = self.controller.report_suspect(new_hazard, 0.71, 3, 60, 600)
        self.assertTrue(decision.allowed)

    def test_timeout_enters_degraded_then_rtl_and_lands(self):
        item = self.dispatch()
        self.controller.apply_verdict(item.event_id, "TIMEOUT", 0.0, 50, 500)
        self.assertEqual(self.controller.states["sentinel"], MissionState.DEGRADED)
        self.assertEqual(self.controller.states["scout"], MissionState.DEGRADED)
        self.controller.begin_rtl(60, 600, "degraded safety return")
        self.controller.mark_landed("sentinel", 70, 700)
        self.controller.mark_landed("scout", 70, 700)
        self.assertEqual(self.controller.states["sentinel"], MissionState.LANDED)
        self.assertEqual(self.controller.states["scout"], MissionState.LANDED)

    def test_stale_target_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "stale"):
            self.controller.report_suspect(
                target(created=0), 0.7, 3, 20, 200000
            )

    def test_mismatched_event_cannot_move_scout(self):
        self.controller.report_suspect(target(), 0.70, 3, 20, 200)
        with self.assertRaisesRegex(ValueError, "active event"):
            self.controller.dispatch_scout("wrong-event", 30, 300)

    def test_suspect_can_be_retained_without_false_scout_takeoff_state(self):
        decision = self.controller.report_suspect(
            target(), 0.70, 3, 20, 200, request_scout=False
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(
            self.controller.states["sentinel"], MissionState.SUSPECT_HOLD
        )
        self.assertEqual(self.controller.states["scout"], MissionState.PREFLIGHT)

    def test_finalized_event_cannot_be_reused(self):
        item = self.dispatch()
        self.controller.apply_verdict(item.event_id, "REJECTED", 0.1, 50, 500)
        with self.assertRaisesRegex(ValueError, "already finalized"):
            self.controller.report_suspect(item, 0.70, 3, 60, 600)


if __name__ == "__main__":
    unittest.main()
