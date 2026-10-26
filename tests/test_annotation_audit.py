import unittest

from tools.audit_fire_annotations import parse_yolo_bbox, size_stratum


class AnnotationAuditTests(unittest.TestCase):
    def test_valid_bbox_is_parsed(self):
        self.assertEqual(parse_yolo_bbox("0 0.5 0.4 0.2 0.1"), (0, (0.5, 0.4, 0.2, 0.1)))

    def test_polygon_or_malformed_row_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_yolo_bbox("0 0.1 0.2 0.3 0.4 0.5 0.6")

    def test_nonfinite_value_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_yolo_bbox("0 0.5 nan 0.2 0.1")

    def test_size_strata_have_documented_boundaries(self):
        self.assertEqual(size_stratum(None), "background")
        self.assertEqual(size_stratum(0.0009), "tiny_lt_0.001")
        self.assertEqual(size_stratum(0.001), "small_0.001_to_0.01")
        self.assertEqual(size_stratum(0.01), "medium_0.01_to_0.10")
        self.assertEqual(size_stratum(0.10), "large_ge_0.10")


if __name__ == "__main__":
    unittest.main()
