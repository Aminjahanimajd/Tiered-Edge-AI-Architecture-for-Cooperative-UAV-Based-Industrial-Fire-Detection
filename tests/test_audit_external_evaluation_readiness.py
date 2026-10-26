import importlib.util
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "audit_external_evaluation_readiness.py"
SPEC = importlib.util.spec_from_file_location("external_readiness", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


@unittest.skipUnless(
    (ROOT / json.loads((ROOT / 'config/external_evaluation_sources_v1.json').read_text(encoding='utf-8'))['sources'][1]['full_frame_decode_manifest']).is_file(),
    'Requires the private external-data decode record; no external model evaluation is implied',
)
class CurrentEvidenceTests(unittest.TestCase):
    def test_current_registry_fails_closed_at_open_gates(self):
        registry = json.loads(
            (ROOT / "config/external_evaluation_sources_v1.json").read_text(encoding="utf-8")
        )
        result = MODULE.audit(registry, ROOT)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["sources"]["fasdd_uav"]["gates"]["license"], "PASS")
        self.assertEqual(result["sources"]["mmodalfire_rgb"]["gates"]["full_decode"], "PASS")
        self.assertIn("fasdd_uav:acquisition", result["blockers"])
        self.assertIn("mmodalfire_rgb:event_condition_alignment", result["blockers"])


if __name__ == "__main__":
    unittest.main()
