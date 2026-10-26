import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "audit_mmodal_media", ROOT / "tools/audit_mmodal_media.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class MmodalMediaAuditTests(unittest.TestCase):
    def test_fractional_rate_is_parsed(self):
        self.assertAlmostEqual(MODULE.rate("30000/1001"), 29.97002997)

    def test_undefined_and_zero_rates_are_none(self):
        self.assertIsNone(MODULE.rate(None))
        self.assertIsNone(MODULE.rate("0/0"))
        self.assertIsNone(MODULE.rate("25/0"))
