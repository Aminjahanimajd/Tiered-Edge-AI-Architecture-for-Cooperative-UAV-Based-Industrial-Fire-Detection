import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "calibration_manifest", ROOT / "tools/build_deployment_calibration_manifest.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CalibrationManifestTests(unittest.TestCase):
    def test_selection_is_balanced_lexical_and_hashed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            base = Path(temporary)
            images = base / "images"
            images.mkdir()
            items = []
            annotations = []
            for index, name in enumerate(("z.jpg", "a.jpg", "y.jpg", "b.jpg"), 1):
                (images / name).write_bytes(name.encode())
                items.append({"id": index, "file_name": name, "width": 10, "height": 8})
            annotations.extend([
                {"id": 1, "image_id": 1, "category_id": 1},
                {"id": 2, "image_id": 2, "category_id": 1},
            ])
            labels = base / "labels.json"
            labels.write_text(json.dumps({"images": items, "annotations": annotations}), encoding="utf-8")
            result = MODULE.build(labels, images, per_stratum=2)
            self.assertEqual(result["image_count"], 4)
            self.assertEqual(
                [row["file_name"] for row in result["records"][:2]], ["a.jpg", "z.jpg"]
            )
            self.assertEqual(
                [row["file_name"] for row in result["records"][2:]], ["b.jpg", "y.jpg"]
            )
            self.assertTrue(all(len(row["sha256"]) == 64 for row in result["records"]))

    def test_insufficient_stratum_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            base = Path(temporary)
            images = base / "images"
            images.mkdir()
            (images / "one.jpg").write_bytes(b"one")
            labels = base / "labels.json"
            labels.write_text(json.dumps({
                "images": [{"id": 1, "file_name": "one.jpg", "width": 1, "height": 1}],
                "annotations": [],
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                MODULE.build(labels, images, per_stratum=1)
