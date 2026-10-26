import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_rejection_memory_grid",
    ROOT / "tools" / "validate_rejection_memory_grid.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RejectionMemoryGridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(
            (ROOT / "config" / "rejection_memory_validation_v1.json").read_text(
                encoding="utf-8"
            )
        )

    def test_grid_has_sixteen_settings(self):
        result = MODULE.run(self.config)
        self.assertEqual(result["evaluated_settings"], 16)

    def test_selects_smallest_shortest_passing_setting(self):
        result = MODULE.run(self.config)
        self.assertEqual(result["selected"], {"radius_m": 0.5, "ttl_s": 15.0})

    def test_zero_ttl_does_not_suppress_repeats(self):
        result = MODULE.evaluate_setting(self.config, 0, 0.5)
        self.assertFalse(result["confounders_suppressed"])
        self.assertFalse(result["passes"])

    def test_too_small_radius_does_not_suppress_largest_jitter(self):
        modified = dict(self.config)
        modified["candidate_radius_m"] = [0.25]
        result = MODULE.evaluate_setting(modified, 15, 0.25)
        self.assertFalse(result["passes"])

    def test_new_target_at_same_location_is_retained(self):
        result = MODULE.evaluate_setting(self.config, 15, 0.5)
        row = next(
            item
            for item in result["safety_observations"]
            if item["case"] == "new_target_same_location"
        )
        self.assertTrue(row["dispatch_allowed"])
        self.assertEqual(row["additional_delay_s"], 0.0)

    def test_persistence_override_is_retained(self):
        result = MODULE.evaluate_setting(self.config, 15, 0.5)
        row = next(
            item
            for item in result["safety_observations"]
            if item["case"] == "persistent_override"
        )
        self.assertTrue(row["dispatch_allowed"])
        self.assertIn("persistent", row["reason"])


if __name__ == "__main__":
    unittest.main()
