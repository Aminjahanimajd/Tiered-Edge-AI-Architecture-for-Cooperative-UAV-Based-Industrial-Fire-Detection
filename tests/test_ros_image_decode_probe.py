import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np


TOOL_PATH = Path(__file__).parents[1] / "tools" / "probe_ros_image_decode.py"
SPEC = importlib.util.spec_from_file_location("probe_ros_image_decode", TOOL_PATH)
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class RosImageDecodeProbeTests(unittest.TestCase):
    def test_decoded_sample_contains_statistics_not_pixels(self):
        message = SimpleNamespace(
            header=SimpleNamespace(
                stamp=SimpleNamespace(sec=1, nanosec=2), frame_id="camera"
            )
        )
        frame = np.full((2, 3, 3), 7, dtype=np.uint8)
        result = PROBE.decoded_sample(
            message,
            frame,
            {"encoding": "yuv422", "decoded_as": "uyvy"},
            0,
            123,
        )
        self.assertEqual(result["bgr_shape"], [2, 3, 3])
        self.assertEqual(result["channel_means_bgr"], [7.0, 7.0, 7.0])
        self.assertNotIn("data", result)


if __name__ == "__main__":
    unittest.main()
