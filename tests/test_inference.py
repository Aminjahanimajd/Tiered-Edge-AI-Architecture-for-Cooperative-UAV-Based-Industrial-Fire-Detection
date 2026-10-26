import unittest

from drone_enhanced_core.inference import (
    compute_resize_transform,
    decode_yolov8,
)


class ArrayWithAmbiguousTruthValue(object):
    """Small NumPy-like array that rejects scalar truth-value evaluation."""

    def __init__(self, values):
        self._values = values
        self.shape = (len(values), len(values[0]))

    def __len__(self):
        return len(self._values)

    def __getitem__(self, index):
        return self._values[index]

    def __bool__(self):
        raise ValueError("truth value is ambiguous")


class InferenceGeometryTests(unittest.TestCase):
    def test_letterbox_undoes_vertical_padding(self):
        transform = compute_resize_transform(640, 480, 640, 640, "letterbox")
        output = [
            [320.0],
            [320.0],
            [64.0],
            [48.0],
            [0.9],
            [0.1],
        ]
        result = decode_yolov8(output, ("fire", "smoke"), transform, 0.5)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].center_u, 0.5)
        self.assertAlmostEqual(result[0].center_v, 0.5)
        self.assertAlmostEqual(result[0].x2 - result[0].x1, 0.1)
        self.assertAlmostEqual(result[0].y2 - result[0].y1, 0.1)

    def test_anchor_first_layout_and_fire_only_policy(self):
        transform = compute_resize_transform(640, 640, 640, 640, "stretch")
        output = [
            [100.0, 100.0, 20.0, 20.0, 0.8, 0.1],
            [200.0, 200.0, 30.0, 30.0, 0.1, 0.95],
        ]
        result = decode_yolov8(
            output,
            ("fire", "smoke"),
            transform,
            0.5,
            allowed_class_names=("fire",),
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].class_name, "fire")

    def test_normalized_output_coordinates_are_scaled_before_letterbox_undo(self):
        transform = compute_resize_transform(1024, 768, 640, 640, "letterbox")
        output = [
            [0.4473751],
            [0.4708319],
            [0.0290170],
            [0.0452159],
            [0.2944458],
            [0.0001],
        ]
        result = decode_yolov8(
            output,
            ("fire", "smoke"),
            transform,
            0.25,
            output_coordinate_space="normalized",
        )
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].center_u, 0.4473751, places=5)
        self.assertAlmostEqual(result[0].center_v, 0.4611092, places=5)
        self.assertAlmostEqual(result[0].x2 - result[0].x1, 0.0290170, places=5)

    def test_rejects_unknown_output_coordinate_space(self):
        transform = compute_resize_transform(640, 640, 640, 640, "stretch")
        with self.assertRaisesRegex(ValueError, "output_coordinate_space"):
            decode_yolov8(
                [[320.0], [320.0], [64.0], [64.0], [0.9], [0.1]],
                ("fire", "smoke"),
                transform,
                0.5,
                output_coordinate_space="auto",
            )

    def test_nms_suppresses_overlapping_same_class(self):
        transform = compute_resize_transform(640, 640, 640, 640, "stretch")
        output = [
            [320.0, 322.0, 100.0],
            [320.0, 322.0, 100.0],
            [100.0, 100.0, 20.0],
            [100.0, 100.0, 20.0],
            [0.9, 0.8, 0.7],
            [0.1, 0.1, 0.1],
        ]
        result = decode_yolov8(output, ("fire", "smoke"), transform, 0.5, 0.45)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].confidence, 0.9)

    def test_rejects_wrong_channel_count(self):
        transform = compute_resize_transform(640, 640, 640, 640)
        with self.assertRaises(ValueError):
            decode_yolov8([[0.0] * 10] * 5, ("fire", "smoke"), transform, 0.5)

    def test_numpy_like_array_is_not_evaluated_as_boolean(self):
        transform = compute_resize_transform(640, 640, 640, 640, "stretch")
        output = ArrayWithAmbiguousTruthValue(
            [
                [320.0],
                [320.0],
                [64.0],
                [64.0],
                [0.9],
                [0.1],
            ]
        )
        result = decode_yolov8(output, ("fire", "smoke"), transform, 0.5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].class_name, "fire")

    def test_numpy_fast_path_matches_portable_decoder(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("NumPy is unavailable in this host runtime")
        transform = compute_resize_transform(640, 480, 640, 640, "letterbox")
        portable = [
            [320.0, 322.0, 500.0, 100.0],
            [320.0, 322.0, 500.0, 100.0],
            [100.0, 100.0, 20.0, 20.0],
            [100.0, 100.0, 20.0, 20.0],
            [0.9, 0.8, 0.1, 0.7],
            [0.1, 0.1, 0.95, 0.1],
        ]
        expected = decode_yolov8(
            portable,
            ("fire", "smoke"),
            transform,
            0.5,
            0.45,
            allowed_class_names=("fire",),
        )
        actual = decode_yolov8(
            np.asarray(portable, dtype=np.float32),
            ("fire", "smoke"),
            transform,
            0.5,
            0.45,
            allowed_class_names=("fire",),
        )
        self.assertEqual(len(actual), len(expected))
        for observed, reference in zip(actual, expected):
            self.assertEqual(observed.class_id, reference.class_id)
            self.assertEqual(observed.class_name, reference.class_name)
            for observed_value, reference_value in zip(
                observed[2:], reference[2:]
            ):
                self.assertAlmostEqual(observed_value, reference_value, places=6)


if __name__ == "__main__":
    unittest.main()
