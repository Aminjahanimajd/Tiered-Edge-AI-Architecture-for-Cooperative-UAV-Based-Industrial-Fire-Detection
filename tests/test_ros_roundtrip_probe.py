import importlib.util
import unittest
from pathlib import Path


TOOL_PATH = Path(__file__).parents[1] / "tools" / "ros_roundtrip_probe.py"
SPEC = importlib.util.spec_from_file_location("ros_roundtrip_probe", TOOL_PATH)
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class RosRoundtripProbeTests(unittest.TestCase):
    def test_rtt_summary_uses_all_observations(self):
        summary = PROBE.summarize_rtt_ms([1.0, 2.0, 3.0])
        self.assertEqual(summary["n"], 3)
        self.assertEqual(summary["mean"], 2.0)
        self.assertEqual(summary["median"], 2.0)
        self.assertEqual(summary["minimum"], 1.0)
        self.assertEqual(summary["maximum"], 3.0)

    def test_empty_rtt_summary_is_explicitly_none(self):
        self.assertIsNone(PROBE.summarize_rtt_ms([]))


if __name__ == "__main__":
    unittest.main()
