import unittest

from tools.quarantine_manifest_source_families import quarantine


class SourceFamilyQuarantineTests(unittest.TestCase):
    def test_quarantine_removes_only_named_families(self):
        records = [
            {"record_id": "a", "source_family_group_id": "keep"},
            {"record_id": "b", "source_family_group_id": "remove"},
            {"record_id": "c", "source_family_group_id": "keep"},
        ]
        retained, removed = quarantine(records, ["remove"])
        self.assertEqual([record["record_id"] for record in retained], ["a", "c"])
        self.assertEqual([record["record_id"] for record in removed], ["b"])


if __name__ == "__main__":
    unittest.main()
