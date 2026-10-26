import importlib.util
import unittest
from pathlib import Path

import numpy as np


TOOL_PATH = Path(__file__).parents[1] / "tools" / "refine_perceptual_duplicates.py"
SPEC = importlib.util.spec_from_file_location("refine_perceptual_duplicates", TOOL_PATH)
REFINEMENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REFINEMENT)


class PerceptualRefinementTests(unittest.TestCase):
    def test_percentile_uses_linear_interpolation(self):
        self.assertEqual(REFINEMENT.percentile([0, 10], 25), 2.5)

    def test_identical_arrays_are_ranked_as_identical(self):
        image = np.zeros((32, 32, 3), dtype=np.float32)
        image[5:20, 7:23, :] = 0.75
        result = REFINEMENT.compare_arrays(image, image.copy())
        self.assertTrue(result["normalized_pixel_identical"])
        self.assertEqual(result["orientation"], "direct")
        self.assertAlmostEqual(result["review_priority_score"], 1.0)

    def test_horizontal_mirror_is_selected_when_it_matches(self):
        first = np.zeros((32, 32, 3), dtype=np.float32)
        first[:, :8, 0] = 1.0
        second = np.flip(first, axis=1).copy()
        result = REFINEMENT.compare_arrays(first, second)
        self.assertTrue(result["normalized_pixel_identical"])
        self.assertEqual(result["orientation"], "second_mirrored")
        self.assertAlmostEqual(result["review_priority_score"], 1.0)

    def test_flat_images_have_undefined_correlation_but_valid_distance(self):
        black = np.zeros((32, 32, 3), dtype=np.float32)
        white = np.ones((32, 32, 3), dtype=np.float32)
        result = REFINEMENT.compare_arrays(black, white)
        self.assertIsNone(result["gray_ncc"])
        self.assertAlmostEqual(result["rgb_mae"], 1.0)
        self.assertFalse(result["normalized_pixel_identical"])


if __name__ == "__main__":
    unittest.main()
