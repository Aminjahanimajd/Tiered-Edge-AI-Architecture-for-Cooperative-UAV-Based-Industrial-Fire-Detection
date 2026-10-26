import importlib.util
import json
import os
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
SPEC = importlib.util.spec_from_file_location(
    "run_mission_logic_pilot",
    os.path.join(ROOT, "tools", "run_mission_logic_pilot.py"),
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MissionLogicPilotTests(unittest.TestCase):
    def test_all_pilot_cases_pass(self):
        result = MODULE.run_pilot()
        self.assertEqual(result["case_count"], 5)
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["failed"], 0)

    def test_repeat_is_suppressed_but_new_target_is_not(self):
        repeat = MODULE.run_case("repeat_suppressed")
        new_target = MODULE.run_case("new_target_same_location")
        self.assertTrue(repeat["success"])
        self.assertEqual(len(repeat["suppressed_detections"]), 1)
        self.assertTrue(new_target["success"])
        self.assertEqual(new_target["suppressed_detections"], [])

    def test_evidence_bundle_is_append_only_and_complete(self):
        result = MODULE.run_pilot()
        with tempfile.TemporaryDirectory() as temporary:
            output = os.path.join(temporary, "pilot")
            manifest = MODULE.write_evidence(ROOT, output, result)
            self.assertEqual(manifest["status"], "PASS")
            self.assertEqual(
                sorted(os.listdir(output)),
                ["manifest.json", "raw_cases.jsonl", "summary.json"],
            )
            with open(os.path.join(output, "raw_cases.jsonl"), encoding="utf-8") as handle:
                self.assertEqual(len(handle.readlines()), 5)
            with self.assertRaises(FileExistsError):
                MODULE.write_evidence(ROOT, output, result)


if __name__ == "__main__":
    unittest.main()
