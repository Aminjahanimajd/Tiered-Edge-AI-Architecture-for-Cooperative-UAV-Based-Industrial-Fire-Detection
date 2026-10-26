import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prepare_dual_px4_sim", ROOT / "tools" / "prepare_dual_px4_sim.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrepareDualPx4SimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = json.loads(
            (ROOT / "config" / "simulation_scenarios_v1.json").read_text(encoding="utf-8")
        )
        cls.measurements = json.loads(
            (ROOT / "simulation" / "airframes" / "airframe_measurements_v1.json").read_text(encoding="utf-8")
        )

    def test_assets_are_distinct_and_match_scenario(self):
        assets = MODULE.validate_assets(ROOT, self.scenarios)
        self.assertEqual(len(assets), 5)
        self.assertNotEqual(
            self.scenarios["vehicles"]["sentinel"]["simulation_model"],
            self.scenarios["vehicles"]["scout"]["simulation_model"],
        )

    def test_formal_measurement_gate_is_closed(self):
        self.assertFalse(MODULE.required_measurements_present(self.measurements))

    def test_complete_measurements_open_gate(self):
        measurements = json.loads(json.dumps(self.measurements))
        measurements["formal_model_generation_allowed"] = True
        measurements["formal_asset_status"] = "MEASURED_PARAMETERS_APPLIED_AND_VERIFIED"
        for vehicle in ("sentinel", "scout"):
            row = measurements[vehicle]
            row.update({
                "mass_with_test_battery_kg": 1.0,
                "rotor_diagonal_m": 0.3,
                "body_length_m": 0.2,
                "body_width_m": 0.2,
                "body_height_m": 0.1,
                "camera_translation_body_frd_m": [0.1, 0.0, 0.0],
                "camera_rotation_body_frd_deg": [0.0, 0.0, 0.0],
                "flight_controller_airframe_id": 4001,
            })
        self.assertTrue(MODULE.required_measurements_present(measurements))

    def test_measurements_alone_do_not_open_formal_gate(self):
        measurements = json.loads(json.dumps(self.measurements))
        measurements["formal_model_generation_allowed"] = True
        self.assertFalse(MODULE.required_measurements_present(measurements))


    def test_launch_contract_uses_unique_identity(self):
        contract = MODULE.launch_contract(Path("/runtime"), self.scenarios)
        sentinel = contract["sentinel"]
        scout = contract["scout"]
        self.assertNotEqual(sentinel["arguments"], scout["arguments"])
        self.assertNotEqual(
            sentinel["environment"]["PX4_UXRCE_DDS_NS"],
            scout["environment"]["PX4_UXRCE_DDS_NS"],
        )
        self.assertEqual(sentinel["expected_dds_key"], sentinel["expected_mavlink_system_id"])
        self.assertEqual(scout["expected_dds_key"], scout["expected_mavlink_system_id"])


if __name__ == "__main__":
    unittest.main()
