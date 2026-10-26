"""Thread-safe latest-frame storage with monotonic freshness checks."""

from __future__ import print_function

import threading


class FrameSnapshot(object):
    __slots__ = ("frame", "monotonic_ns", "sequence")

    def __init__(self, frame, monotonic_ns, sequence):
        self.frame = frame
        self.monotonic_ns = int(monotonic_ns)
        self.sequence = int(sequence)


class LatestFrameBuffer(object):
    """Store one frame; callers receive a copy that cannot race with writers."""

    def __init__(self):
        self._lock = threading.Lock()
        self._frame = None
        self._monotonic_ns = None
        self._sequence = 0

    def update(self, frame, monotonic_ns):
        if frame is None:
            raise ValueError("frame cannot be None")
        monotonic_ns = int(monotonic_ns)
        if monotonic_ns < 0:
            raise ValueError("monotonic_ns cannot be negative")
        with self._lock:
            self._frame = frame.copy()
            self._monotonic_ns = monotonic_ns
            self._sequence += 1
            return self._sequence

    def snapshot(self, now_ns, max_age_ns):
        now_ns = int(now_ns)
        max_age_ns = int(max_age_ns)
        if max_age_ns < 0:
            raise ValueError("max_age_ns cannot be negative")
        with self._lock:
            if self._frame is None:
                return None, "NO_FRAME"
            age_ns = now_ns - self._monotonic_ns
            if age_ns < 0:
                return None, "CLOCK_REGRESSION"
            if age_ns > max_age_ns:
                return None, "STALE_FRAME"
            return (
                FrameSnapshot(
                    self._frame.copy(), self._monotonic_ns, self._sequence
                ),
                "FRESH",
            )
