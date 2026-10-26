import importlib.util
import unittest
from pathlib import Path


TOOL_PATH = Path(__file__).parents[1] / "tools" / "analyze_ros_roundtrip.py"
SPEC = importlib.util.spec_from_file_location("analyze_ros_roundtrip", TOOL_PATH)
ANALYSIS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYSIS)


class RosRoundtripAnalysisTests(unittest.TestCase):
    def test_timing_summary_preserves_tail_counts(self):
        summary = ANALYSIS.timing_summary([1.0, 2.0, 3.0, 101.0])
        self.assertEqual(summary["n"], 4)
        self.assertEqual(summary["count_above_10_ms"], 1)
        self.assertEqual(summary["count_above_100_ms"], 1)

    def test_timing_summary_requires_values(self):
        with self.assertRaises(ValueError):
            ANALYSIS.timing_summary([])


if __name__ == "__main__":
    unittest.main()
