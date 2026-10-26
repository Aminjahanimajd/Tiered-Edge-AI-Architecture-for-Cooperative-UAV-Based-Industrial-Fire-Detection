import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np


TOOL_PATH = (
    Path(__file__).parents[1]
    / "ros2_ws"
    / "src"
    / "drone_enhanced_nodes"
    / "drone_enhanced_nodes"
    / "runtime_support.py"
)
SPEC = importlib.util.spec_from_file_location("runtime_support", TOOL_PATH)
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


class RuntimeSupportImageDecodeTests(unittest.TestCase):
    @staticmethod
    def fake_cv2():
        def convert(array, _conversion):
            return np.zeros((array.shape[0], array.shape[1], 3), dtype=np.uint8)

        return SimpleNamespace(
            COLOR_GRAY2BGR=0,
            COLOR_YUV2BGR_UYVY=1,
            COLOR_YUV2BGR_YUY2=2,
            COLOR_YUV2BGR_NV12=3,
            COLOR_YUV2BGR_NV21=4,
            COLOR_RGB2BGR=5,
            cvtColor=convert,
        )

    def test_live_scout_mono8_geometry_decodes_to_bgr(self):
        width = 4
        height = 2
        payload = np.arange(width * height, dtype=np.uint8).tobytes()
        message = SimpleNamespace(
            data=payload,
            width=width,
            height=height,
            step=width,
            encoding="mono8",
        )
        with mock.patch.dict(sys.modules, {"cv2": self.fake_cv2()}):
            frame, metadata = RUNTIME.decode_ros_image_to_bgr(message)
        self.assertEqual(frame.shape, (height, width, 3))
        self.assertEqual(metadata["decoded_as"], "mono8")
        self.assertEqual(metadata["data_length"], len(payload))

    def test_mono8_rejects_inconsistent_step(self):
        message = SimpleNamespace(
            data=bytes(8), width=4, height=2, step=5, encoding="mono8"
        )
        with mock.patch.dict(sys.modules, {"cv2": self.fake_cv2()}):
            with self.assertRaisesRegex(ValueError, "step"):
                RUNTIME.decode_ros_image_to_bgr(message)

    def test_live_scout_yuv422_geometry_decodes_as_uyvy(self):
        width = 4
        height = 2
        payload = np.full(width * height * 2, 128, dtype=np.uint8).tobytes()
        message = SimpleNamespace(
            data=payload,
            width=width,
            height=height,
            step=width * 2,
            encoding="yuv422",
        )
        with mock.patch.dict(sys.modules, {"cv2": self.fake_cv2()}):
            frame, metadata = RUNTIME.decode_ros_image_to_bgr(message)
        self.assertEqual(frame.shape, (height, width, 3))
        self.assertEqual(metadata["decoded_as"], "uyvy")
        self.assertEqual(metadata["data_length"], len(payload))

    def test_yuv422_rejects_inconsistent_step(self):
        message = SimpleNamespace(
            data=bytes(16), width=4, height=2, step=7, encoding="yuv422"
        )
        with mock.patch.dict(sys.modules, {"cv2": self.fake_cv2()}):
            with self.assertRaisesRegex(ValueError, "step"):
                RUNTIME.decode_ros_image_to_bgr(message)

    def test_sentinel_gstreamer_pipeline_matches_live_d435i_format(self):
        pipeline = RUNTIME.build_gstreamer_yuy2_pipeline(
            "/dev/video2", 640, 480, 30
        )
        self.assertIn("device=/dev/video2", pipeline)
        self.assertIn("format=YUY2", pipeline)
        self.assertIn("format=BGR", pipeline)
        self.assertIn("drop=true max-buffers=1 sync=false", pipeline)

    def test_sentinel_pipeline_rejects_non_device_path(self):
        with self.assertRaisesRegex(ValueError, "/dev/video"):
            RUNTIME.build_gstreamer_yuy2_pipeline("2", 640, 480, 30)


if __name__ == "__main__":
    unittest.main()
