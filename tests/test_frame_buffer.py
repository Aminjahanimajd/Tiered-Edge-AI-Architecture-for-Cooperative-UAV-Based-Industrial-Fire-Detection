import unittest

from drone_enhanced_core.frame_buffer import LatestFrameBuffer


class CopyableFrame(object):
    def __init__(self, value):
        self.value = value

    def copy(self):
        return CopyableFrame(self.value)


class FrameBufferTests(unittest.TestCase):
    def test_reports_no_frame_and_stale_frame(self):
        buffer = LatestFrameBuffer()
        self.assertEqual(buffer.snapshot(100, 10)[1], "NO_FRAME")
        buffer.update(CopyableFrame(1), 100)
        self.assertEqual(buffer.snapshot(111, 10)[1], "STALE_FRAME")

    def test_returns_independent_fresh_copy(self):
        buffer = LatestFrameBuffer()
        original = CopyableFrame(7)
        buffer.update(original, 100)
        original.value = 99
        snapshot, status = buffer.snapshot(105, 10)
        self.assertEqual(status, "FRESH")
        self.assertEqual(snapshot.frame.value, 7)
        snapshot.frame.value = 4
        second, _ = buffer.snapshot(106, 10)
        self.assertEqual(second.frame.value, 7)


if __name__ == "__main__":
    unittest.main()
