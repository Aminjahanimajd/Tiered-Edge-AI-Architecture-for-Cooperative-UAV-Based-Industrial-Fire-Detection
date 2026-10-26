import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "extract_mmodal_alignment_frames",
    ROOT / "tools/extract_mmodal_alignment_frames.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class MmodalAlignmentFrameTests(unittest.TestCase):
    def test_long_video_uses_five_second_edges(self):
        self.assertEqual(
            MODULE.sample_times(100.0),
            [("start", 5.0), ("middle", 50.0), ("end", 95.0)],
        )

    def test_short_video_samples_are_distinct(self):
        values = MODULE.sample_times(4.0)
        self.assertEqual(values, [("start", 1.0), ("middle", 2.0), ("end", 3.0)])

    def test_nonpositive_duration_is_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.sample_times(0.0)
