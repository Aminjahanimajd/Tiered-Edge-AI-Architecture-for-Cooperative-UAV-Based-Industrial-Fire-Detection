import importlib.util
import pathlib
import unittest


MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "tools"
    / "ocr_mmodal_alignment_timestamps_v2.py"
)
SPEC = importlib.util.spec_from_file_location("mmodal_ocr_v2", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ParseTimestampTests(unittest.TestCase):
    def test_parses_digit_only_ocr_with_spurious_separator_digits(self):
        self.assertEqual(
            MODULE.parse_timestamp("2022470801-15:59:51"),
            "2022-08-01T15:59:51",
        )

    def test_parses_clean_date_and_time(self):
        self.assertEqual(
            MODULE.parse_timestamp("2022/08/10 16:38:52"),
            "2022-08-10T16:38:52",
        )

    def test_parses_clock_attached_to_date_digits(self):
        self.assertEqual(
            MODULE.parse_timestamp("202247080209:33:31"),
            "2022-08-02T09:33:31",
        )

    def test_ignores_trailing_ocr_digit_after_seconds(self):
        self.assertEqual(
            MODULE.parse_timestamp("2022470804/15:46:435"),
            "2022-08-04T15:46:43",
        )

    def test_rejects_missing_full_date(self):
        self.assertIsNone(MODULE.parse_timestamp("15:59:51"))

    def test_rejects_invalid_clock(self):
        self.assertIsNone(MODULE.parse_timestamp("2022/08/10 29:99:99"))


if __name__ == "__main__":
    unittest.main()
