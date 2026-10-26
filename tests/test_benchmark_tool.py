import importlib.util
import unittest
from pathlib import Path


TOOL_PATH = Path(__file__).parents[1] / "tools" / "benchmark_device_backend.py"
SPEC = importlib.util.spec_from_file_location("benchmark_device_backend", TOOL_PATH)
BENCHMARK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


class BenchmarkToolTests(unittest.TestCase):
    def test_percentile_uses_documented_linear_interpolation(self):
        self.assertEqual(BENCHMARK.percentile([1, 2, 3, 4, 5], 50), 3.0)
        self.assertEqual(BENCHMARK.percentile([0, 10], 25), 2.5)

    def test_summary_preserves_sample_count_and_population_statistics(self):
        summary = BENCHMARK.summarize([1, 2, 3])
        self.assertEqual(summary["n"], 3)
        self.assertEqual(summary["mean"], 2.0)
        self.assertEqual(summary["median"], 2.0)
        self.assertEqual(summary["range"], 2.0)
        self.assertAlmostEqual(summary["population_variance"], 2.0 / 3.0)


if __name__ == "__main__":
    unittest.main()
