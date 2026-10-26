import unittest

from tools.evaluate_coco_predictions import (
    intersection_over_union,
    select_threshold,
    threshold_metrics,
    validate_inputs,
)


class CommonCocoEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.ground_truth = {
            "images": [{"id": 1}, {"id": 2}],
            "categories": [{"id": 1, "name": "fire"}],
            "annotations": [
                {"id": 1, "image_id": 1, "category_id": 1, "bbox": [0, 0, 10, 10]}
            ],
        }

    def test_iou_uses_xywh_boxes(self):
        self.assertAlmostEqual(
            intersection_over_union([0, 0, 10, 10], [5, 0, 10, 10]), 1.0 / 3.0
        )

    def test_threshold_metrics_preserve_background_false_positive_rate(self):
        predictions = [
            {"image_id": 1, "category_id": 1, "bbox": [0, 0, 10, 10], "score": 0.9},
            {"image_id": 2, "category_id": 1, "bbox": [0, 0, 5, 5], "score": 0.8},
        ]
        result = threshold_metrics(self.ground_truth, predictions, 0.5)
        self.assertEqual((result["tp"], result["fp"], result["fn"]), (1, 1, 0))
        self.assertEqual(result["background_images"], 1)
        self.assertEqual(result["background_false_positive_image_rate"], 1.0)

    def test_threshold_selection_maximizes_f1_then_recall(self):
        predictions = [
            {"image_id": 1, "category_id": 1, "bbox": [0, 0, 10, 10], "score": 0.4},
            {"image_id": 2, "category_id": 1, "bbox": [0, 0, 5, 5], "score": 0.2},
        ]
        selected = select_threshold(self.ground_truth, predictions)
        self.assertEqual(selected["tp"], 1)
        self.assertEqual(selected["fp"], 0)
        self.assertAlmostEqual(selected["threshold"], 0.21)

    def test_validation_rejects_unknown_image(self):
        predictions = [
            {"image_id": 99, "category_id": 1, "bbox": [0, 0, 1, 1], "score": 0.5}
        ]
        with self.assertRaises(ValueError):
            validate_inputs(self.ground_truth, predictions)

    def test_relative_box_area_recall_is_reported_when_dimensions_exist(self):
        ground_truth = {
            "images": [{"id": 1, "width": 100, "height": 100}],
            "categories": [{"id": 1, "name": "fire"}],
            "annotations": [
                {"id": 1, "image_id": 1, "category_id": 1, "bbox": [0, 0, 5, 5]}
            ],
        }
        predictions = [
            {"image_id": 1, "category_id": 1, "bbox": [0, 0, 5, 5], "score": 0.9}
        ]
        result = threshold_metrics(ground_truth, predictions, 0.5)
        very_small = result["ground_truth_recall_by_relative_box_area"][
            "very_small_lt_1pct"
        ]
        self.assertEqual(very_small["ground_truth_boxes"], 1)
        self.assertEqual(very_small["matched_boxes"], 1)
        self.assertEqual(very_small["recall"], 1.0)


if __name__ == "__main__":
    unittest.main()
