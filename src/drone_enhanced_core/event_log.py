"""Bounded non-blocking JSONL event logger with explicit drop accounting."""

from __future__ import print_function

import json
import os
import queue
import threading


class AsyncJsonlLogger(object):
    """Open one append-only file and write records from a dedicated thread."""

    _STOP = object()

    def __init__(self, path, max_queue_size=4096, flush_every=1):
        self.path = os.path.abspath(path)
        self.max_queue_size = int(max_queue_size)
        self.flush_every = int(flush_every)
        if self.max_queue_size <= 0:
            raise ValueError("max_queue_size must be positive")
        if self.flush_every <= 0:
            raise ValueError("flush_every must be positive")

        parent = os.path.dirname(self.path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        self._queue = queue.Queue(maxsize=self.max_queue_size)
        self._closed = False
        self._dropped = 0
        self._written = 0
        self._error = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._writer, name="jsonl-writer")
        self._thread.daemon = True
        self._thread.start()

    @property
    def dropped_records(self):
        with self._lock:
            return self._dropped

    @property
    def written_records(self):
        with self._lock:
            return self._written

    def log(self, record):
        if not isinstance(record, dict):
            raise TypeError("record must be a dictionary")
        if self._closed:
            raise RuntimeError("logger is closed")
        if self._error is not None:
            raise RuntimeError("logger writer failed: {}".format(self._error))
        try:
            self._queue.put_nowait(dict(record))
            return True
        except queue.Full:
            with self._lock:
                self._dropped += 1
            return False

    def _writer(self):
        since_flush = 0
        try:
            with open(self.path, "a", encoding="utf-8") as output:
                while True:
                    item = self._queue.get()
                    try:
                        if item is self._STOP:
                            break
                        output.write(json.dumps(item, sort_keys=True, separators=(",", ":")))
                        output.write("\n")
                        since_flush += 1
                        with self._lock:
                            self._written += 1
                        if since_flush >= self.flush_every:
                            output.flush()
                            since_flush = 0
                    finally:
                        self._queue.task_done()
                output.flush()
                os.fsync(output.fileno())
        except Exception as exc:
            self._error = exc

    def close(self, timeout_seconds=10.0):
        if self._closed:
            return
        self._closed = True
        self._queue.put(self._STOP)
        self._thread.join(float(timeout_seconds))
        if self._thread.is_alive():
            raise RuntimeError("logger did not stop within timeout")
        if self._error is not None:
            raise RuntimeError("logger writer failed: {}".format(self._error))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
