import unittest

from tools.regroup_manifest_from_review import (
    DisjointGroups,
    assign_preserving_existing_splits,
    component_identifier,
    regroup,
)


class RegroupManifestTests(unittest.TestCase):
    def test_component_identifier_is_order_independent(self):
        self.assertEqual(component_identifier(["b", "a"]), component_identifier(["a", "b"]))

    def test_reviewed_same_scene_and_uncertain_edges_are_merged(self):
        records = [
            {"record_id": "r1", "group_id": "a", "split": "train"},
            {"record_id": "r2", "group_id": "b", "split": "valid"},
            {"record_id": "r3", "group_id": "c", "split": "test"},
        ]
        decisions = [
            {
                "review_index": "1",
                "visual_label": "visually_same_scene",
                "first_group_id": "a",
                "second_group_id": "b",
            },
            {
                "review_index": "2",
                "visual_label": "uncertain_related_sequence",
                "first_group_id": "b",
                "second_group_id": "c",
            },
        ]
        used, components = regroup(records, decisions)
        self.assertEqual(len(used), 2)
        self.assertEqual(len(components), 1)
        self.assertEqual(len({record["group_id"] for record in records}), 1)
        self.assertTrue(all("split" not in record for record in records))

    def test_not_visibly_same_edge_is_not_merged(self):
        groups = DisjointGroups(["a", "b"])
        self.assertNotEqual(groups.find("a"), groups.find("b"))

    def test_preserved_assignment_changes_only_cross_split_component(self):
        records = [
            {"record_id": "r1", "group_id": "merged", "previous_split": "train", "category": "background"},
            {"record_id": "r2", "group_id": "merged", "previous_split": "test", "category": "background"},
            {"record_id": "r3", "group_id": "fixed", "previous_split": "valid", "category": "fire_positive"},
        ]
        actual, _, _ = assign_preserving_existing_splits(records)
        self.assertEqual([record["split"] for record in records], ["train", "train", "valid"])
        self.assertEqual(actual["train"]["background"], 2)
        self.assertEqual(actual["valid"]["positive"], 1)


if __name__ == "__main__":
    unittest.main()
