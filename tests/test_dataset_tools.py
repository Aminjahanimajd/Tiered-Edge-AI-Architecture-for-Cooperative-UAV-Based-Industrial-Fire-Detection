import unittest

from tools.build_fire_manifest import assign_groups, validate


class DatasetSplitToolTests(unittest.TestCase):
    def test_global_group_assignment_populates_all_splits_without_leakage(self):
        records = []
        for group_number in range(60):
            category = "background" if group_number % 5 == 0 else "fire_positive"
            for member in range(3):
                records.append(
                    {
                        "record_id": "record-{}-{}".format(group_number, member),
                        "group_id": "group-{}".format(group_number),
                        "category": category,
                    }
                )
        actual, _, _ = assign_groups(records, seed=7)
        self.assertTrue(all(actual[split]["total"] > 0 for split in actual))
        self.assertEqual(validate(records), 60)
        group_splits = {}
        for record in records:
            group_splits.setdefault(record["group_id"], set()).add(record["split"])
        self.assertTrue(all(len(splits) == 1 for splits in group_splits.values()))


if __name__ == "__main__":
    unittest.main()
