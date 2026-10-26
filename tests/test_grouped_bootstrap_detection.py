import unittest

from tools.grouped_bootstrap_detection import add_counts, metric_values


class GroupedBootstrapTests(unittest.TestCase):
    def test_metric_values_from_counts(self):
        values = metric_values(
            {
                "tp": 8,
                "fp": 2,
                "fn": 2,
                "background_images": 5,
                "background_images_with_prediction": 1,
            }
        )
        self.assertAlmostEqual(values["precision"], 0.8)
        self.assertAlmostEqual(values["recall"], 0.8)
        self.assertAlmostEqual(values["f1"], 0.8)
        self.assertAlmostEqual(values["background_false_positive_image_rate"], 0.2)

    def test_add_counts_accumulates_all_denominators(self):
        target = {
            "tp": 0,
            "fp": 0,
            "fn": 0,
            "background_images": 0,
            "background_images_with_prediction": 0,
        }
        add_counts(
            target,
            {"tp": 1, "fp": 2, "fn": 3, "background_images": 4, "background_images_with_prediction": 2},
        )
        self.assertEqual(target, {"tp": 1, "fp": 2, "fn": 3, "background_images": 4, "background_images_with_prediction": 2})


if __name__ == "__main__":
    unittest.main()
