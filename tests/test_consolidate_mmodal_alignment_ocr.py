import importlib.util
import pathlib
import unittest


MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "tools"
    / "consolidate_mmodal_alignment_ocr.py"
)
SPEC = importlib.util.spec_from_file_location("consolidate_mmodal_ocr", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def row(label, offset, frame_hash, clock=None, timestamp=None):
    value = {
        "sample_label": label,
        "requested_offset_seconds": offset,
        "source_frame_sha256": frame_hash,
    }
    if clock is not None:
        value["parsed_clock_hh_mm_ss"] = clock
    if timestamp is not None:
        value["parsed_timestamp"] = timestamp
    return value


class ConsolidationTests(unittest.TestCase):
    def test_accepts_unique_cross_pass_progression(self):
        v1 = [
            row("start", 5, "a", "10:00:05"),
            row("middle", 65, "b", "10:01:05"),
            row("end", 125, "c", "10:02:05"),
        ]
        v2 = [
            row("start", 5, "a", timestamp="2022-08-02T10:00:05"),
            row("middle", 65, "b"),
            row("end", 125, "c"),
        ]
        result = MODULE.consolidate_video(v1, v2)
        self.assertEqual(result["status"], "PASS")

    def test_rejects_mismatched_frame_identity(self):
        result = MODULE.consolidate_video(
            [row("start", 5, "a", "10:00:05")],
            [row("start", 5, "different", timestamp="2022-08-02T10:00:05")],
        )
        self.assertEqual(result["reason"], "FRAME_IDENTITY_MISMATCH")

    def test_rejects_ambiguous_video_date(self):
        v1 = [row("start", 5, "a", "10:00:05"), row("end", 65, "b", "10:01:05")]
        v2 = [
            row("start", 5, "a", timestamp="2022-08-02T10:00:05"),
            row("end", 65, "b", timestamp="2022-08-03T10:01:05"),
        ]
        result = MODULE.consolidate_video(v1, v2)
        self.assertEqual(result["reason"], "NO_UNIQUE_VIDEO_DATE")


if __name__ == "__main__":
    unittest.main()
