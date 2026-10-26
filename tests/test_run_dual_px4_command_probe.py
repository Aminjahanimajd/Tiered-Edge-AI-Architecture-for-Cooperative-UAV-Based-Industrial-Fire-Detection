import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "run_dual_px4_command_probe",
    ROOT / "tools/run_dual_px4_command_probe.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DualPx4CommandProbeTests(unittest.TestCase):
    def test_parser_finds_result_after_logging_noise(self):
        result = MODULE.parse_result('noise\n{"status":"PASS","vehicle_id":"sentinel"}\n')
        self.assertEqual(result["status"], "PASS")

    def test_parser_rejects_missing_result(self):
        with self.assertRaises(ValueError):
            MODULE.parse_result("no result")

    def test_probe_targets_are_distinct_and_bounded(self):
        self.assertNotEqual(
            MODULE.VEHICLE_PROBES["sentinel"],
            MODULE.VEHICLE_PROBES["scout"],
        )
        for row in MODULE.VEHICLE_PROBES.values():
            east, north, up = row["target_enu"]
            self.assertTrue(0 <= east <= 20)
            self.assertTrue(0 <= north <= 30)
            self.assertTrue(0 <= up <= 8)
