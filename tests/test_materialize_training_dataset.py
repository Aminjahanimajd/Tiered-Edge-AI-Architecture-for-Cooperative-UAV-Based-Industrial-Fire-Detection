import tempfile
import unittest
from pathlib import Path

from tools.materialize_training_dataset import materialized_name, materialize


class MaterializeTrainingDatasetTests(unittest.TestCase):
    def test_materializes_image_and_empty_background_label(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.jpg"
            source.write_bytes(b"image-bytes")
            output = root / "output"
            output.mkdir()
            record = {
                "record_id": "negative/example.jpg",
                "image_path": str(source),
                "split": "train",
                "category": "background",
                "derived_label_rows": [],
            }
            rows = materialize([record], output)
            name = materialized_name(record)
            self.assertEqual((output / "images" / "train" / name).read_bytes(), b"image-bytes")
            self.assertEqual((output / "labels" / "train" / (Path(name).stem + ".txt")).read_text(), "")
            self.assertEqual(rows[0]["box_count"], 0)

    def test_rejects_unknown_split(self):
        with tempfile.TemporaryDirectory() as temporary:
            record = {
                "record_id": "r",
                "image_path": str(Path(temporary) / "missing.jpg"),
                "split": "holdout",
                "category": "background",
            }
            with self.assertRaises(ValueError):
                materialize([record], Path(temporary))


if __name__ == "__main__":
    unittest.main()
