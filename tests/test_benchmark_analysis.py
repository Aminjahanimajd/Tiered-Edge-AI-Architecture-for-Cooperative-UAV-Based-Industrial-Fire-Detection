import importlib.util
import unittest
from pathlib import Path


TOOL_PATH = Path(__file__).parents[1] / "tools" / "analyze_backend_benchmarks.py"
SPEC = importlib.util.spec_from_file_location("analyze_backend_benchmarks", TOOL_PATH)
ANALYSIS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYSIS)


class BenchmarkAnalysisTests(unittest.TestCase):
    def test_comparison_uses_scout_as_relative_latency_baseline(self):
        result = ANALYSIS.compare_devices(200.0, 1000.0)
        self.assertEqual(result["scout_to_sentinel_mean_pipeline_latency_ratio"], 5.0)
        self.assertEqual(
            result[
                "sentinel_mean_pipeline_latency_reduction_relative_to_scout_percent"
            ],
            80.0,
        )

    def test_comparison_rejects_nonpositive_latency(self):
        with self.assertRaises(ValueError):
            ANALYSIS.compare_devices(0.0, 1000.0)


if __name__ == "__main__":
    unittest.main()
