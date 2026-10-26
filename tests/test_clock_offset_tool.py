import importlib.util
import unittest
from pathlib import Path


TOOL_PATH = Path(__file__).parents[1] / "tools" / "measure_remote_clock_offset.py"
SPEC = importlib.util.spec_from_file_location("measure_remote_clock_offset", TOOL_PATH)
CLOCK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLOCK)


class ClockOffsetToolTests(unittest.TestCase):
    def test_summary_selects_minimum_round_trip_sample(self):
        samples = [
            {
                "sample_index": 0,
                "round_trip_monotonic_ns": 100,
                "remote_minus_local_midpoint_ns": 4,
                "uncertainty_plus_or_minus_ns": 50,
            },
            {
                "sample_index": 1,
                "round_trip_monotonic_ns": 20,
                "remote_minus_local_midpoint_ns": 8,
                "uncertainty_plus_or_minus_ns": 10,
            },
        ]
        summary = CLOCK.summarize_samples(samples)
        self.assertEqual(summary["best_sample_index"], 1)
        self.assertEqual(summary["best_remote_minus_local_midpoint_ns"], 8)
        self.assertEqual(summary["best_uncertainty_plus_or_minus_ns"], 10)

    def test_summary_requires_samples(self):
        with self.assertRaises(ValueError):
            CLOCK.summarize_samples([])


if __name__ == "__main__":
    unittest.main()
