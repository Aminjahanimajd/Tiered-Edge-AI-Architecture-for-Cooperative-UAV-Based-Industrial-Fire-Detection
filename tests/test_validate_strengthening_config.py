import copy
import importlib.util
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
SPEC = importlib.util.spec_from_file_location(
    "validate_strengthening_config",
    os.path.join(ROOT, "tools", "validate_strengthening_config.py"),
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StrengtheningConfigTests(unittest.TestCase):
    def setUp(self):
        self.project = MODULE.load_json(
            os.path.join(ROOT, "config", "project_strengthening_v1.json")
        )
        self.scenarios = MODULE.load_json(
            os.path.join(ROOT, "config", "simulation_scenarios_v1.json")
        )
        self.airframes = MODULE.load_json(
            os.path.join(
                ROOT, "simulation", "airframes", "airframe_measurements_v1.json"
            )
        )
        self.runtime = MODULE.load_json(
            os.path.join(ROOT, "simulation", "runtime_lock.json")
        )

    def validate(self):
        return MODULE.validate(
            self.project, self.scenarios, self.airframes, self.runtime
        )

    def test_frozen_contract_is_valid(self):
        self.assertEqual(self.validate(), [])

    def test_identical_airframe_models_are_rejected(self):
        self.scenarios["vehicles"]["scout"]["simulation_model"] = (
            self.scenarios["vehicles"]["sentinel"]["simulation_model"]
        )
        self.assertTrue(any("distinct" in item for item in self.validate()))

    def test_duplicate_vehicle_namespace_is_rejected(self):
        self.scenarios["vehicles"]["scout"]["ros_namespace"] = "/sentinel"
        self.assertTrue(any("unique" in item for item in self.validate()))

    def test_formal_airframe_freeze_requires_measurements(self):
        self.airframes["formal_model_generation_allowed"] = True
        self.assertTrue(any("missing physical" in item for item in self.validate()))

    def test_external_training_use_must_remain_prohibited(self):
        project = copy.deepcopy(self.project)
        project["external_data"]["training_use_prohibited"] = False
        errors = MODULE.validate(
            project, self.scenarios, self.airframes, self.runtime
        )
        self.assertTrue(any("prohibited" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
