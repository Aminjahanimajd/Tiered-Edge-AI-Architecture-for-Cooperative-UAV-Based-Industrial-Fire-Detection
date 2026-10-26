import copy
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_contracts",
    ROOT / "tools" / "validate_deployment_and_external_contracts.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class DeploymentAndExternalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deployment = json.loads(
            (ROOT / "config/model_deployment_registry_v1.json").read_text(encoding="utf-8")
        )
        cls.external = json.loads(
            (ROOT / "config/external_evaluation_sources_v1.json").read_text(encoding="utf-8")
        )

    @unittest.skipUnless(
        (ROOT / 'artifacts/experiments/deployment_calibration_native_v1/manifest.json').is_file(),
        'Requires the complete private native calibration/model archive',
    )
    def test_current_contracts_are_valid(self):
        self.assertEqual(MODULE.validate(self.deployment, self.external), [])

    def test_missing_candidate_is_rejected(self):
        deployment = copy.deepcopy(self.deployment)
        deployment["models"].pop()
        errors = MODULE.validate(deployment, self.external)
        self.assertTrue(any("six models" in error for error in errors))

    def test_unfrozen_outcome_is_rejected(self):
        deployment = copy.deepcopy(self.deployment)
        deployment["models"][0]["platform_attempts"]["sentinel_jetson_nano"] = {
            "outcome": "MAYBE"
        }
        errors = MODULE.validate(deployment, self.external)
        self.assertTrue(any("invalid outcome" in error for error in errors))

    @unittest.skipUnless(
        (ROOT / 'artifacts/experiments/model_screening_v1/yolov8n_416_screen_seed_20260729/weights/best.pt').is_file(),
        'Requires the private historical model bytes to exercise a hash mismatch',
    )
    def test_hash_mismatch_is_rejected(self):
        deployment = copy.deepcopy(self.deployment)
        deployment["models"][0]["native_artifacts"][0]["sha256"] = "0" * 64
        errors = MODULE.validate(deployment, self.external)
        self.assertTrue(any("hash mismatch" in error for error in errors))

    @unittest.skipUnless(
        (ROOT / 'artifacts/experiments/deployment_calibration_native_v1/manifest.json').is_file(),
        'Requires the private native calibration manifest to exercise a hash mismatch',
    )
    def test_calibration_evidence_hash_mismatch_is_rejected(self):
        deployment = copy.deepcopy(self.deployment)
        deployment["canonical_calibration_evidence_sha256"] = "0" * 64
        errors = MODULE.validate(deployment, self.external)
        self.assertTrue(any("calibration evidence hash mismatch" in error for error in errors))

    def test_external_training_use_is_rejected(self):
        external = copy.deepcopy(self.external)
        external["training_use_permitted"] = True
        errors = MODULE.validate(self.deployment, external)
        self.assertTrue(any("training" in error for error in errors))

    def test_admission_requires_license_manifest_and_overlap(self):
        external = copy.deepcopy(self.external)
        external["sources"][0]["admission_status"] = "ADMITTED"
        external["sources"][0]["license_identifier"] = None
        external["sources"][0]["license_evidence_path"] = None
        errors = MODULE.validate(self.deployment, external)
        self.assertGreaterEqual(
            len([error for error in errors if "fasdd_uav" in error]), 3
        )

    def test_mmodal_condition_hash_mismatch_is_rejected(self):
        external = copy.deepcopy(self.external)
        external["sources"][1]["publisher_condition_table"][
            "derived_table_sha256"
        ] = "0" * 64
        errors = MODULE.validate(self.deployment, external)
        self.assertTrue(
            any("condition table hash mismatch" in error for error in errors)
        )

    def test_mmodal_completed_alignment_cannot_be_claimed(self):
        external = copy.deepcopy(self.external)
        external["sources"][1]["publisher_condition_table"][
            "video_alignment_status"
        ] = "PASS"
        errors = MODULE.validate(self.deployment, external)
        self.assertTrue(any("alignment status was overstated" in error for error in errors))
