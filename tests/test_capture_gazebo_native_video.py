import importlib.util
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "capture_gazebo_native_video", ROOT / "tools" / "capture_gazebo_native_video.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GazeboNativeVideoTests(unittest.TestCase):
    def test_request_requires_true_response(self):
        completed = mock.Mock(returncode=0, stdout="data: true\n", stderr="")
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed) as call:
            result = MODULE.screenshot_request(Path("/tmp/scene"))
        self.assertTrue(result["passed"])
        self.assertIn(str(Path("/tmp/scene")), call.call_args.args[0][-1])

    def test_request_rejects_transport_timeout(self):
        completed = mock.Mock(returncode=1, stdout="", stderr="timeout")
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed):
            self.assertFalse(MODULE.screenshot_request(Path("/tmp/scene"))["passed"])

    def test_capture_contract_rejects_invalid_count_and_rate(self):
        with self.assertRaisesRegex(ValueError, "at least 2"):
            MODULE.run(Path("unused"), 1, 2.0)
        with self.assertRaisesRegex(ValueError, "positive"):
            MODULE.run(Path("unused"), 2, 0.0)


if __name__ == "__main__":
    unittest.main()
