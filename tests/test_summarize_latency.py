import unittest

from tools.summarize_latency import percentile


class LatencySummaryTests(unittest.TestCase):
    def test_linear_percentile(self):
        self.assertEqual(percentile([0.0, 10.0], 0.5), 5.0)
        self.assertEqual(percentile([3.0, 1.0, 2.0], 0.5), 2.0)


if __name__ == "__main__":
    unittest.main()
