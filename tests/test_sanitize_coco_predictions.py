import unittest

from tools.sanitize_coco_predictions import sanitize


class SanitizeCocoPredictionsTests(unittest.TestCase):
    def test_only_degenerate_boxes_are_excluded(self):
        predictions = [
            {"bbox": [0, 0, 1, 2]},
            {"bbox": [0, 0, 0, 2]},
            {"bbox": [0, 0, 1, float("nan")]},
        ]
        retained, excluded = sanitize(predictions)
        self.assertEqual(retained, [predictions[0]])
        self.assertEqual([item["index"] for item in excluded], [1, 2])


if __name__ == "__main__":
    unittest.main()
