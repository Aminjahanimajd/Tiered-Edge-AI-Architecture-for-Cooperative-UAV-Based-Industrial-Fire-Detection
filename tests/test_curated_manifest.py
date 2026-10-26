import unittest

from tools.build_curated_research_manifest import curate_records


class CuratedManifestTests(unittest.TestCase):
    def test_excludes_configured_group_and_caps_deterministically(self):
        records = [
            {"record_id": "drop", "group_id": "excluded", "split": "test"},
            {"record_id": "a", "group_id": "kept", "split": "train"},
            {"record_id": "b", "group_id": "kept", "split": "valid"},
            {"record_id": "c", "group_id": "kept", "split": "test"},
        ]
        first, excluded, capped = curate_records(records, {"excluded"}, 2, 7)
        second, _, _ = curate_records(records, {"excluded"}, 2, 7)
        self.assertEqual([item["record_id"] for item in first], [item["record_id"] for item in second])
        self.assertEqual([item["record_id"] for item in excluded], ["drop"])
        self.assertEqual(len(first), 2)
        self.assertNotIn("split", first[0])
        self.assertEqual(capped["kept"], {"before": 3, "after": 2})

    def test_missing_excluded_group_is_rejected(self):
        with self.assertRaises(ValueError):
            curate_records([{"record_id": "a", "group_id": "kept"}], {"absent"}, 2, 7)


if __name__ == "__main__":
    unittest.main()
