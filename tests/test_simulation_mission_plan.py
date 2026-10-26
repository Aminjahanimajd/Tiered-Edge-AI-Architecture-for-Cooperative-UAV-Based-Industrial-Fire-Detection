import json
import unittest
from pathlib import Path

from drone_enhanced_core.px4_sim_adapter import EnuPosition
from drone_enhanced_core.simulation_mission_plan import (
    build_hierarchical_plan,
    lawnmower_waypoints,
    standoff_position,
)


ROOT = Path(__file__).resolve().parents[1]
SCENARIO_PATH = ROOT / "config" / "simulation_scenarios_v2.json"


class SimulationMissionPlanTests(unittest.TestCase):
    def setUp(self):
        self.configuration = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))

    def test_lawnmower_alternates_direction_and_includes_boundaries(self):
        points = lawnmower_waypoints(
            {
                "minimum_east_m": 1.0,
                "maximum_east_m": 7.0,
                "minimum_north_m": 2.0,
                "maximum_north_m": 8.0,
            },
            altitude_m=5.5,
            lane_spacing_m=3.0,
        )
        self.assertEqual(
            points,
            (
                EnuPosition(1.0, 2.0, 5.5),
                EnuPosition(1.0, 8.0, 5.5),
                EnuPosition(4.0, 8.0, 5.5),
                EnuPosition(4.0, 2.0, 5.5),
                EnuPosition(7.0, 2.0, 5.5),
                EnuPosition(7.0, 8.0, 5.5),
            ),
        )

    def test_confirmed_plan_uses_distinct_homes_and_safe_standoff(self):
        plan = build_hierarchical_plan(
            self.configuration, "scenario-fire-tank-a"
        )
        self.assertEqual(plan.expected_verdict, "CONFIRMED")
        self.assertEqual(plan.sentinel_home, EnuPosition(0.0, 0.0, 0.0))
        self.assertEqual(plan.scout_home, EnuPosition(-4.0, 0.0, 0.0))
        target = EnuPosition(12.0, 5.0, 4.0)
        distance = (
            (plan.scout_standoff.position_enu.east_m - target.east_m) ** 2
            + (plan.scout_standoff.position_enu.north_m - target.north_m) ** 2
        ) ** 0.5
        self.assertAlmostEqual(distance, 3.0)
        self.assertGreater(
            plan.scout_standoff.position_enu.up_m,
            self.configuration["environment"]["highest_modeled_obstacle_m"],
        )

    def test_plan_contains_scout_return_at_negative_east_home(self):
        plan = build_hierarchical_plan(
            self.configuration, "scenario-reflection-pipe-b"
        )
        self.assertEqual(plan.expected_verdict, "REJECTED")
        self.assertEqual(plan.scout_rtl.position_enu.east_m, -4.0)
        self.assertEqual(
            plan.scout_rtl.position_enu.up_m,
            self.configuration["mission"]["scout_transit_altitude_m"],
        )

    def test_clearance_violation_fails_closed(self):
        self.configuration["mission"]["scout_transit_altitude_m"] = 4.5
        with self.assertRaisesRegex(ValueError, "clearance"):
            build_hierarchical_plan(
                self.configuration, "scenario-fire-tank-a"
            )

    def test_unknown_event_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            build_hierarchical_plan(self.configuration, "missing-event")

    def test_standoff_requires_positive_distance(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            standoff_position(
                EnuPosition(1.0, 1.0, 0.0),
                EnuPosition(0.0, 0.0, 0.0),
                0.0,
                5.0,
            )


if __name__ == "__main__":
    unittest.main()
