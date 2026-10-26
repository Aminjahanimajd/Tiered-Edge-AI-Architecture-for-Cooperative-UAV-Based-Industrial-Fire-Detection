import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_mmodal_conditions",
    ROOT / "tools/validate_mmodal_condition_table.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class MmodalConditionTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = json.loads(
            (ROOT / "config/mmodalfire_condition_table_v1.json").read_text(
                encoding="utf-8"
            )
        )

    def test_publisher_table_contract_passes(self):
        errors, summary = MODULE.validate(self.table)
        self.assertEqual(errors, [])
        self.assertEqual(summary["row_count"], 38)
        self.assertEqual(summary["group_counts"], MODULE.EXPECTED_GROUPS)

    def test_duplicate_condition_is_rejected(self):
        table = copy.deepcopy(self.table)
        table[2][0] = table[1][0]
        errors, _ = MODULE.validate(table)
        self.assertTrue(any("not unique" in error for error in errors))

    def test_invalid_time_is_rejected(self):
        table = copy.deepcopy(self.table)
        table[1][5] = "unknown"
        errors, _ = MODULE.validate(table)
        self.assertTrue(any("invalid publisher time" in error for error in errors))
