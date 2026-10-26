import json
import tempfile
import unittest
from pathlib import Path

from tools.validate_screening_contract import source_record_summary


class ScreeningContractTests(unittest.TestCase):
    def test_source_record_summary_checks_membership_and_groups(self):
        records = [
            {"record_id": "a", "group_id": "g1", "split": "valid"},
            {"record_id": "b", "group_id": "g1", "split": "valid"},
            {"record_id": "c", "group_id": "g2", "split": "test"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
            result = source_record_summary(path, [{"record_id": "a"}, {"record_id": "b"}])
        self.assertEqual(result["record_count"], 2)
        self.assertEqual(result["source_group_count"], 1)
        self.assertEqual(result["duplicate_record_ids"], 0)
        self.assertEqual(result["coco_records_missing_from_manifest"], 0)
        self.assertEqual(result["manifest_records_missing_from_coco"], 0)


if __name__ == "__main__":
    unittest.main()
