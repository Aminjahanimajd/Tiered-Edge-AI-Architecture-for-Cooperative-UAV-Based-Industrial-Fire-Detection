import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prepare_formal_simulation_campaign",
    ROOT / "tools/prepare_formal_simulation_campaign.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FormalSimulationCampaignPlanTests(unittest.TestCase):
    def setUp(self):
        self.campaign = MODULE.load_json(
            ROOT / "config/formal_simulation_campaign_v1.json"
        )
        self.project = MODULE.load_json(
            ROOT / "config/project_strengthening_v1.json"
        )

    def test_plan_has_preregistered_counts_unique_ids_and_seeds(self):
        rows = MODULE.build_plan(self.campaign, self.project)
        self.assertEqual(MODULE.validate_plan(rows, self.campaign, self.project), [])
        self.assertEqual(len(rows), 310)
        self.assertEqual(len({row["run_id"] for row in rows}), 310)
        self.assertEqual(len({row["seed"] for row in rows}), 310)

    def test_plan_order_and_seed_are_deterministic(self):
        first = MODULE.build_plan(self.campaign, self.project)
        second = MODULE.build_plan(self.campaign, self.project)
        self.assertEqual(first, second)

    def test_visual_capture_is_preregistered_for_seventeen_runs(self):
        rows = MODULE.build_plan(self.campaign, self.project)
        selected = [row for row in rows if row["capture_visual"]]
        self.assertEqual(len(selected), 17)

    def test_prepare_retains_plan_but_blocks_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "plan"
            manifest = MODULE.prepare(ROOT, output)
            self.assertEqual(manifest["status"], "PLAN_READY")
            self.assertFalse(manifest["execution_authorized"])
            self.assertEqual(manifest["readiness_status"], "BLOCKED")
            rows = [
                json.loads(line)
                for line in (output / "planned_runs.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(rows), 310)
            with self.assertRaises(FileExistsError):
                MODULE.prepare(ROOT, output)


if __name__ == "__main__":
    unittest.main()
