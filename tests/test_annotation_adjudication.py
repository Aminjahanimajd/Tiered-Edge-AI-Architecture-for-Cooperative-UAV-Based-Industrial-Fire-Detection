import unittest

from tools.apply_annotation_adjudication import apply_actions, summarize


class AnnotationAdjudicationTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"record_id": "a", "derived_label_rows": ["0 a", "0 b"], "split": "train", "group_id": "g1", "category": "fire_positive"},
            {"record_id": "b", "derived_label_rows": ["0 c"], "split": "test", "group_id": "g2", "category": "fire_positive"},
        ]
        self.decisions = [
            {"queue_index": "1", "record_id": "a"},
            {"queue_index": "2", "record_id": "b"},
        ]

    def test_filters_indexed_boxes_and_excludes_record(self):
        output, actions = apply_actions(
            self.records,
            self.decisions,
            {"exclude_record_indices": "2", "keep_box_indices_by_queue_index": {"1": "2"}},
        )
        self.assertEqual([record["record_id"] for record in output], ["a"])
        self.assertEqual(output[0]["derived_label_rows"], ["0 b"])
        self.assertEqual(actions["removed_box_count"], 2)

    def test_rejects_empty_filtered_positive(self):
        with self.assertRaises(ValueError):
            apply_actions(
                self.records,
                self.decisions,
                {"exclude_record_indices": "2", "keep_box_indices_by_queue_index": {"1": "3"}},
            )

    def test_summary_rejects_cross_split_group(self):
        records = [dict(self.records[0]), dict(self.records[1])]
        records[1]["group_id"] = "g1"
        with self.assertRaises(ValueError):
            summarize(records)


if __name__ == "__main__":
    unittest.main()
