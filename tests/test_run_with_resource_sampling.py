import unittest

from tools.run_with_resource_sampling import finite_summary


class ResourceSamplingTests(unittest.TestCase):
    def test_finite_summary_ignores_missing_values(self):
        summary = finite_summary([1.0, None, 3.0])
        self.assertEqual(summary["sample_count"], 2)
        self.assertEqual(summary["mean"], 2.0)
        self.assertEqual(summary["minimum"], 1.0)
        self.assertEqual(summary["maximum"], 3.0)

    def test_empty_summary_is_explicit(self):
        summary = finite_summary([None])
        self.assertEqual(summary["sample_count"], 0)
        self.assertIsNone(summary["mean"])


if __name__ == "__main__":
    unittest.main()
