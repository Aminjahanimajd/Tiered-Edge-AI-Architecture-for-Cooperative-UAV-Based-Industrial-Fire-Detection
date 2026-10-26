import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DDS = load("run_dual_px4_dds_probe")
ROS = load("run_dual_px4_ros_graph_probe")


class DualPx4DdsAndRosProbeTests(unittest.TestCase):
    def test_agent_analysis_requires_distinct_created_clients(self):
        text = "\n".join([
            "debug client_key: 0x00000099",
            "info create_client create | client_key: 0x00000003, session_id: 0x81",
            "info create_client create | client_key: 0x00000002, session_id: 0x81",
        ])
        result = DDS.analyze_agent(text)
        self.assertTrue(result["passed"])
        self.assertEqual(result["observed_client_keys"], ["00000002", "00000003"])
        self.assertFalse(DDS.analyze_agent(text.replace("00000002", "00000004"))["passed"])

    def test_topic_parser_preserves_namespaces_and_types(self):
        text = "\n".join([
            "/sentinel/fmu/out/vehicle_status_v1 [px4_msgs/msg/VehicleStatus]",
            "/scout/fmu/out/vehicle_status_v1 [px4_msgs/msg/VehicleStatus]",
            "invalid line",
        ])
        topics = ROS.parse_topic_list(text)
        self.assertEqual(len(topics), 2)
        self.assertEqual(
            topics["/sentinel/fmu/out/vehicle_status_v1"],
            "px4_msgs/msg/VehicleStatus",
        )
        self.assertIn("/scout/fmu/out/vehicle_status_v1", topics)

    def test_required_contract_covers_both_vehicles(self):
        self.assertTrue(any(name.startswith("/sentinel/") for name in ROS.REQUIRED))
        self.assertTrue(any(name.startswith("/scout/") for name in ROS.REQUIRED))
        self.assertEqual(len(ROS.REQUIRED), len(set(ROS.REQUIRED)))


if __name__ == "__main__":
    unittest.main()
