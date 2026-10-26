import importlib.util
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "audit_exact_device_screening_readiness.py"
SPEC = importlib.util.spec_from_file_location("device_readiness", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


@unittest.skipUnless(
    all(
        (ROOT / artifact['path']).is_file()
        for model in json.loads((ROOT / 'config/exact_device_screening_v1.json').read_text(encoding='utf-8'))['models']
        for artifact in [model.get('native_artifact', {})] + model.get('additional_native_artifacts', []) + model.get('prepared_artifacts', [])
        if artifact.get('path')
    ),
    'Requires private original/converted model artifacts, intentionally excluded from the public archive',
)
class CurrentPreparationTests(unittest.TestCase):
    def test_integrity_and_executor_pass_but_devices_block(self):
        matrix = json.loads(
            (ROOT / "config/exact_device_screening_v1.json").read_text(encoding="utf-8")
        )
        project = json.loads(
            (ROOT / "config/project_strengthening_v1.json").read_text(encoding="utf-8")
        )
        result = MODULE.audit(matrix, project, ROOT)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["fidelity_valid_converted_artifact_count"], 2)
        self.assertEqual(result["fidelity_rejected_converted_artifact_count"], 3)
        self.assertEqual(result["native_tflite_candidate_count"], 1)
        self.assertTrue(
            all(
                artifact["status"] == "PASS"
                for model in result["models"]
                for artifact in model["artifacts"]
            )
        )
        self.assertTrue(result["executor_present"])
        self.assertEqual(
            result["blockers"], ["both physical edge devices are not yet marked READY"]
        )


if __name__ == "__main__":
    unittest.main()
