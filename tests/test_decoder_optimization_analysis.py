import importlib.util
import unittest
from pathlib import Path


TOOL_PATH = (
    Path(__file__).parents[1] / "tools" / "compare_decoder_optimization.py"
)
SPEC = importlib.util.spec_from_file_location("compare_decoder_optimization", TOOL_PATH)
COMPARISON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPARISON)


class DecoderOptimizationAnalysisTests(unittest.TestCase):
    def test_relative_reduction_uses_baseline_denominator(self):
        self.assertEqual(COMPARISON.relative_reduction_percent(200.0, 50.0), 75.0)

    def test_relative_reduction_rejects_invalid_baseline(self):
        with self.assertRaises(ValueError):
            COMPARISON.relative_reduction_percent(0.0, 1.0)


if __name__ == "__main__":
    unittest.main()
