import importlib.util
import unittest
from pathlib import Path


TOOL_PATH = Path(__file__).parents[1] / "tools" / "apply_manual_duplicate_review.py"
SPEC = importlib.util.spec_from_file_location("apply_manual_duplicate_review", TOOL_PATH)
REVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REVIEW)


class ManualDuplicateReviewTests(unittest.TestCase):
    def test_index_ranges_are_inclusive_and_one_based(self):
        self.assertEqual(REVIEW.parse_index_ranges("1-3,5,7-8"), [1, 2, 3, 5, 7, 8])

    def test_overlapping_classifications_are_rejected(self):
        with self.assertRaises(ValueError):
            REVIEW.build_labels({"same": "1-2", "different": "2-3"}, 3)

    def test_every_queue_row_requires_a_label(self):
        with self.assertRaises(ValueError):
            REVIEW.build_labels({"same": "1-2"}, 3)


if __name__ == "__main__":
    unittest.main()
