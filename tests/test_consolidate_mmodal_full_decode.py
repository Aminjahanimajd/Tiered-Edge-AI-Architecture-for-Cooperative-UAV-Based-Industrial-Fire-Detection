import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "consolidate_mmodal_full_decode",
    ROOT / "tools/consolidate_mmodal_full_decode.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ConsolidateMmodalDecodeTests(unittest.TestCase):
    def test_latest_completed_attempt_is_selected(self):
        attempts = [
            (Path("attempt_1.json"), {"status": "FAIL"}),
            (Path("attempt_2.json"), {"status": "PASS"}),
            (
                Path("attempt_3.json"),
                {"status": "DECODE_PASS_METADATA_COUNT_MISMATCH"},
            ),
        ]
        selected = MODULE.select_completion(attempts)
        self.assertIsNotNone(selected)
        self.assertEqual(selected[0], Path("attempt_3.json"))

    def test_failed_attempt_is_not_completion(self):
        self.assertIsNone(
            MODULE.select_completion([(Path("attempt_1.json"), {"status": "FAIL"})])
        )
