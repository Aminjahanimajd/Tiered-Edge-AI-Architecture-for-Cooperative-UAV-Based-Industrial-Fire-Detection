import unittest

import numpy as np

from tools.predict_tflite_coco import dequantize, prepare_input


class TflitePreprocessingTests(unittest.TestCase):
    def test_float_scale_and_offset_support_normalized_export_contract(self):
        rgb = np.array([[[0, 127, 255]]], dtype=np.uint8)
        detail = {"dtype": np.float32, "quantization": (0.0, 0)}
        result = prepare_input(rgb, detail, 2.0 / 255.0, "raw_pixels", -1.0)
        np.testing.assert_allclose(
            result,
            np.array([[[[-1.0, -0.00392157, 1.0]]]], dtype=np.float32),
            atol=1e-6,
        )

    def test_uint8_unquantized_input_preserves_pixels(self):
        rgb = np.array([[[0, 127, 255]]], dtype=np.uint8)
        detail = {"dtype": np.uint8, "quantization": (0.0, 0)}
        result = prepare_input(rgb, detail, 1.0)
        self.assertEqual(result.shape, (1, 1, 1, 3))
        np.testing.assert_array_equal(result[0], rgb)

    def test_quantized_input_clips_to_dtype(self):
        rgb = np.array([[[0, 255, 100]]], dtype=np.uint8)
        detail = {"dtype": np.int8, "quantization": (1.0, -128)}
        result = prepare_input(rgb, detail, 1.0, "quantize_scaled")
        np.testing.assert_array_equal(result[0, 0, 0], [-128, 127, -28])

    def test_uint8_quantized_raw_pixel_mode_preserves_pixels(self):
        rgb = np.array([[[0, 127, 255]]], dtype=np.uint8)
        detail = {"dtype": np.uint8, "quantization": (0.0078125, 127)}
        result = prepare_input(rgb, detail, 1.0, "raw_pixels")
        np.testing.assert_array_equal(result[0], rgb)

    def test_dequantize_applies_scale_and_zero_point(self):
        values = np.array([-128, -28, 127], dtype=np.int8)
        detail = {"quantization": (0.5, -128)}
        np.testing.assert_allclose(dequantize(values, detail), [0.0, 50.0, 127.5])


if __name__ == "__main__":
    unittest.main()
