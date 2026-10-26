import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ocr_mmodal_alignment_timestamps",
    ROOT / "tools/ocr_mmodal_alignment_timestamps.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class MmodalTimestampOcrTests(unittest.TestCase):
    def test_last_valid_clock_is_selected(self):
        self.assertEqual(
            MODULE.parse_clock("noise 01:02:03 timestamp 15:59:51"), "15:59:51"
        )

    def test_invalid_clock_is_not_parsed(self):
        self.assertIsNone(MODULE.parse_clock("2022708 401A"))
        self.assertIsNone(MODULE.parse_clock("25:01:01"))

    def test_clock_delta_wraps_at_midnight(self):
        self.assertEqual(MODULE.circular_delta_seconds("23:59:58", "00:00:03"), 5)
