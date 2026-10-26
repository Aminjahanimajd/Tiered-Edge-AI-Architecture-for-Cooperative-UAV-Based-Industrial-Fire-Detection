import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "audit_formal_simulation_readiness",
    ROOT / "tools/audit_formal_simulation_readiness.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FormalSimulationReadinessTests(unittest.TestCase):
    def test_current_development_assets_are_blocked_honestly(self):
        result = MODULE.audit(ROOT)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["planned_runs"]["total"], 310)
        joined = "\n".join(result["blockers"])
        self.assertIn("physical airframe characterization is incomplete", joined)
        self.assertIn("mission-node-restart Gazebo development pilot", joined)
        self.assertNotIn("mode is not implemented", joined)
        self.assertIn("repeated-confounder Gazebo development pilot", joined)
        self.assertIn("repeated_confounder", result["runner_modes"])
        self.assertIn("repeated_confounder", result["mission_node_modes"])

    def test_fault_choices_are_extracted_from_both_entry_points(self):
        runner = MODULE.fault_choices(
            ROOT / "tools/run_hierarchical_px4_mission.py"
        )
        node = MODULE.fault_choices(
            ROOT / "tools/px4_sim_hierarchical_mission.py"
        )
        self.assertIn("low_battery", runner)
        self.assertIn("duplicate_or_stale_verdict", node)
        self.assertIn("mission_node_restart", runner)
        self.assertIn("mission_node_restart", node)

    def test_output_is_created_once_and_preserves_status(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "readiness.json"
            status = MODULE.main(["--root", str(ROOT), "--output", str(output)])
            self.assertEqual(status, 2)
            self.assertEqual(json.loads(output.read_text())["status"], "BLOCKED")
            with self.assertRaises(FileExistsError):
                MODULE.main(["--root", str(ROOT), "--output", str(output)])


if __name__ == "__main__":
    unittest.main()
