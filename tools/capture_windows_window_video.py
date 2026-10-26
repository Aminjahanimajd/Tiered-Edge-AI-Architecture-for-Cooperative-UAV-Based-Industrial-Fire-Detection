#!/usr/bin/env python3
"""Continuously record one visible Windows window to a timestamped AVI.

This utility is intentionally window-scoped: it does not capture unrelated
desktop content. It is launched by the WSL Gazebo orchestrator and stops when
the supplied sentinel file appears.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import datetime
import json
import re
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import ImageGrab


user32 = ctypes.windll.user32


def visible_windows(pattern):
    matches = []
    regex = re.compile(pattern, re.IGNORECASE)

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value
        if not regex.search(title):
            return True
        rect = ctypes.wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width > 320 and height > 240 and not user32.IsIconic(hwnd):
                matches.append((width * height, int(hwnd), title, rect))
        return True

    user32.EnumWindows(callback, 0)
    return sorted(matches, reverse=True)


def run(output, stop_file, fps, title_regex, wait_s):
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass
    deadline = time.monotonic() + wait_s
    match = None
    while time.monotonic() < deadline and not stop_file.exists():
        rows = visible_windows(title_regex)
        if rows:
            match = rows[0]
            break
        time.sleep(0.25)
    if match is None:
        raise RuntimeError(f"no visible window matched {title_regex!r}")

    _, hwnd, title, rect = match
    left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
    width = (right - left) - ((right - left) % 2)
    height = (bottom - top) - ((bottom - top) % 2)
    bbox = (left, top, left + width, top + height)
    output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output), cv2.VideoWriter_fourcc(*"MJPG"), float(fps), (width, height)
    )
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not initialize the MJPG recorder")

    started = datetime.datetime.now(datetime.timezone.utc)
    ready = output.with_suffix(".ready.json")
    timing = output.with_suffix(".frames.jsonl")
    interval = 1.0 / float(fps)
    frames = 0
    with timing.open("w", encoding="utf-8") as timing_stream:
        try:
            while not stop_file.exists():
                tick = time.perf_counter()
                image = ImageGrab.grab(bbox=bbox, all_screens=True).convert("RGB")
                frame = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
                writer.write(frame)
                frames += 1
                captured = datetime.datetime.now(datetime.timezone.utc).isoformat()
                timing_stream.write(json.dumps({
                    "frame": frames,
                    "captured_utc": captured,
                    "window_title": title,
                    "window_handle": hwnd,
                    "bbox": list(bbox),
                }, sort_keys=True) + "\n")
                if frames == 1:
                    ready.write_text(json.dumps({
                        "status": "READY",
                        "window_title": title,
                        "window_handle": hwnd,
                        "bbox": list(bbox),
                        "fps": fps,
                        "started_utc": started.isoformat(),
                    }, indent=2) + "\n", encoding="utf-8")
                remaining = interval - (time.perf_counter() - tick)
                if remaining > 0:
                    time.sleep(remaining)
        finally:
            writer.release()
    summary = {
        "status": "PASS" if frames >= 2 else "FAIL",
        "window_title": title,
        "window_handle": hwnd,
        "bbox": list(bbox),
        "fps": fps,
        "frame_count": frames,
        "started_utc": started.isoformat(),
        "completed_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "output": str(output),
        "timing_log": str(timing),
    }
    output.with_suffix(".manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))
    return summary["status"] == "PASS"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--title-regex", default=r"Gazebo|industrial_inspection")
    parser.add_argument("--wait-s", type=float, default=90.0)
    args = parser.parse_args()
    return 0 if run(
        args.output, args.stop_file, args.fps, args.title_regex, args.wait_s
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
