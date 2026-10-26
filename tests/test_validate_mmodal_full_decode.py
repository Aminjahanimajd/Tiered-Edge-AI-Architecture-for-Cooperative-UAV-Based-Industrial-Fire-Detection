import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_mmodal_full_decode", ROOT / "tools/validate_mmodal_full_decode.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class MmodalFullDecodeTests(unittest.TestCase):
    def test_parse_progress_keeps_final_values(self):
        parsed = MODULE.parse_progress("frame=10\nprogress=continue\nframe=25\nprogress=end\n")
        self.assertEqual(parsed["frame"], "25")
        self.assertEqual(parsed["progress"], "end")

    def test_prior_pass_requires_hash_and_decoder_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "status": "PASS",
                "source_sha256": "abc",
                "decoder": {"version": "ffmpeg version 6.1.1"},
            }
            (root / "attempt_1.json").write_text(json.dumps(payload), encoding="utf-8")
            self.assertTrue(MODULE.prior_pass_exists(root, "abc", "ffmpeg version 6.1.1"))
            self.assertFalse(MODULE.prior_pass_exists(root, "different", "ffmpeg version 6.1.1"))
            self.assertFalse(MODULE.prior_pass_exists(root, "abc", "ffmpeg version 7"))

    def test_safe_id_is_deterministic_and_path_safe(self):
        value = MODULE.safe_id("sub/odd name.mp4")
        self.assertEqual(value, MODULE.safe_id("sub/odd name.mp4"))
        self.assertNotIn("/", value)
        self.assertNotIn(" ", value)

    def test_successful_decode_can_retain_metadata_warning(self):
        self.assertEqual(
            MODULE.classify_decode(
                returncode=0,
                hash_ok=True,
                progress_complete=True,
                frame_count_ok=False,
            ),
            "DECODE_PASS_METADATA_COUNT_MISMATCH",
        )

    def test_decoder_error_is_failure(self):
        self.assertEqual(
            MODULE.classify_decode(
                returncode=1,
                hash_ok=True,
                progress_complete=False,
                frame_count_ok=True,
            ),
            "FAIL",
        )
