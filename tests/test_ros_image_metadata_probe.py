import importlib.util
import unittest
from pathlib import Path


TOOL_PATH = Path(__file__).parents[1] / "tools" / "probe_ros_image_metadata.py"
SPEC = importlib.util.spec_from_file_location("probe_ros_image_metadata", TOOL_PATH)
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class RosImageMetadataProbeTests(unittest.TestCase):
    def test_expected_nv12_payload_length(self):
        self.assertEqual(PROBE.expected_payload_bytes(1024, 768, "NV12"), 1179648)

    def test_summary_does_not_include_pixel_content(self):
        samples = [
            {
                "sample_index": 0,
                "arrival_monotonic_ns": 1000000000,
                "header_stamp_sec": 1,
                "header_stamp_nanosec": 2,
                "frame_id": "camera",
                "height": 768,
                "width": 1024,
                "encoding": "NV12",
                "is_bigendian": 0,
                "step": 1024,
                "data_length": 1179648,
            },
            {
                "sample_index": 1,
                "arrival_monotonic_ns": 1033000000,
                "header_stamp_sec": 1,
                "header_stamp_nanosec": 33000002,
                "frame_id": "camera",
                "height": 768,
                "width": 1024,
                "encoding": "NV12",
                "is_bigendian": 0,
                "step": 1024,
                "data_length": 1179648,
            },
        ]
        result = PROBE.summarize(samples, "/camera", 2, 5.0)
        self.assertTrue(result["complete"])
        self.assertTrue(result["payload_matches_encoding"])
        self.assertFalse(result["pixel_content_persisted"])
        self.assertAlmostEqual(
            result["arrival_interval_summary"]["mean_ms"], 33.0
        )


if __name__ == "__main__":
    unittest.main()
