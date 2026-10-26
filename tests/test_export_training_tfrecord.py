import json
import tempfile
import unittest
from pathlib import Path

from tools.export_training_tfrecord import label_map_text, validate_coco_export


class ExportTrainingTfRecordTests(unittest.TestCase):
    def test_one_class_label_map_uses_tensorflow_one_based_id(self):
        self.assertEqual(label_map_text(), "item {\n  id: 1\n  name: 'fire'\n}\n")

    def test_rejects_changed_coco_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            summary = {"split_results": {}}
            for split in ("train", "valid", "test"):
                directory = root / split
                directory.mkdir()
                labels = directory / "labels.json"
                labels.write_text(json.dumps({"split": split}), encoding="utf-8")
                summary["split_results"][split] = {
                    "labels_json_sha256": "incorrect"
                }
            with self.assertRaises(ValueError):
                validate_coco_export(root, summary)


if __name__ == "__main__":
    unittest.main()
