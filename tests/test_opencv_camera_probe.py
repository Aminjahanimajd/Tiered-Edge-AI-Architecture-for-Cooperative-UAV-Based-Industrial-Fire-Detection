import importlib.util
import unittest
from pathlib import Path


TOOL_PATH = Path(__file__).parents[1] / "tools" / "probe_opencv_camera.py"
SPEC = importlib.util.spec_from_file_location("probe_opencv_camera", TOOL_PATH)
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class OpenCvCameraProbeTests(unittest.TestCase):
    def test_fourcc_decoding(self):
        integer = ord("M") | ord("J") << 8 | ord("P") << 16 | ord("G") << 24
        self.assertEqual(PROBE.fourcc_text(integer), "MJPG")

    def test_interval_summary_is_population_based(self):
        result = PROBE.summarize_intervals([30.0, 40.0])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["mean_ms"], 35.0)
        self.assertEqual(result["population_standard_deviation_ms"], 5.0)

    def test_gstreamer_pipeline_is_explicit_and_low_latency(self):
        pipeline = PROBE.build_gstreamer_pipeline("/dev/video2", 640, 480, 30)
        self.assertIn("format=YUY2", pipeline)
        self.assertIn("format=BGR", pipeline)
        self.assertIn("max-buffers=1", pipeline)
        self.assertIn("drop=true", pipeline)


if __name__ == "__main__":
    unittest.main()
