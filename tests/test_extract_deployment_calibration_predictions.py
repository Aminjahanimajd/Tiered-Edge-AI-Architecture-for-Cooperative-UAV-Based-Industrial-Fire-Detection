import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "extract_deployment_calibration_predictions",
    ROOT / "tools" / "extract_deployment_calibration_predictions.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DeploymentCalibrationExtractionTests(unittest.TestCase):
    def test_registry_contains_exact_six_candidates(self):
        self.assertEqual(len(MODULE.SOURCE_RUNS), 6)
        self.assertEqual(len(MODULE.SOURCE_RUNS), len(set(MODULE.SOURCE_RUNS)))

    def test_prediction_filter_retains_only_selected_ids(self):
        rows = [
            {"image_id": 1, "score": 0.8},
            {"image_id": 2, "score": 0.7},
            {"image_id": 3, "score": 0.6},
        ]
        self.assertEqual(
            MODULE.filter_predictions(rows, {1, 3}),
            [rows[0], rows[2]],
        )

    def test_latency_filter_requires_every_calibration_image(self):
        rows = [{"image_id": "1", "inference_ms": "2.0"}]
        with self.assertRaisesRegex(ValueError, "missing 1"):
            MODULE.filter_latency_rows(rows, {1, 2})
        self.assertEqual(MODULE.filter_latency_rows(rows, {1}), rows)


if __name__ == "__main__":
    unittest.main()
