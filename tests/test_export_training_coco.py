import unittest

from tools.export_training_coco import yolo_row_to_coco


class ExportTrainingCocoTests(unittest.TestCase):
    def test_yolo_box_converts_to_absolute_top_left_coco_box(self):
        self.assertEqual(
            yolo_row_to_coco("0 0.5 0.5 0.25 0.5", 400, 200),
            [150.0, 50.0, 100.0, 100.0],
        )

    def test_rejects_non_fire_or_malformed_row(self):
        with self.assertRaises(ValueError):
            yolo_row_to_coco("1 0.5 0.5 0.2 0.2", 100, 100)


if __name__ == "__main__":
    unittest.main()
