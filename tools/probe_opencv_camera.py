#!/usr/bin/env python3
"""Collect bounded OpenCV camera metadata and pixel statistics without images."""

from __future__ import print_function

import argparse
import json
import statistics
import sys
import time


def fourcc_text(value):
    integer = int(round(value))
    return "".join(chr((integer >> (8 * index)) & 0xFF) for index in range(4))


def summarize_intervals(intervals_ms):
    if not intervals_ms:
        return None
    return {
        "count": len(intervals_ms),
        "mean_ms": statistics.mean(intervals_ms),
        "median_ms": statistics.median(intervals_ms),
        "minimum_ms": min(intervals_ms),
        "maximum_ms": max(intervals_ms),
        "population_standard_deviation_ms": statistics.pstdev(intervals_ms),
    }


def build_gstreamer_pipeline(device, width, height, fps):
    return (
        "v4l2src device={} ! "
        "video/x-raw, format=YUY2, width={}, height={}, framerate={}/1 ! "
        "videoconvert ! video/x-raw, format=BGR ! "
        "appsink drop=true max-buffers=1 sync=false"
    ).format(device, int(width), int(height), int(fps))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="2")
    parser.add_argument("--backend", choices=("v4l2", "gstreamer"), default="v4l2")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--sample-count", type=int, default=10)
    parser.add_argument("--maximum-attempts", type=int, default=30)
    arguments = parser.parse_args()
    if min(arguments.width, arguments.height, arguments.sample_count) <= 0:
        parser.error("width, height, and sample count must be positive")
    if arguments.maximum_attempts < arguments.sample_count:
        parser.error("maximum attempts must be at least the sample count")

    import cv2
    import numpy as np

    pipeline = None
    if arguments.backend == "gstreamer":
        pipeline = build_gstreamer_pipeline(
            arguments.device, arguments.width, arguments.height, arguments.fps
        )
        camera = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    else:
        device = (
            int(arguments.device) if arguments.device.isdigit() else arguments.device
        )
        camera = cv2.VideoCapture(device, cv2.CAP_V4L2)
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, arguments.width)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, arguments.height)
        camera.set(cv2.CAP_PROP_FPS, arguments.fps)
    result = {
        "schema_version": 1,
        "probe_type": "opencv_camera_metadata_and_statistics",
        "pixel_content_persisted": False,
        "device": arguments.device,
        "backend": arguments.backend,
        "pipeline": pipeline,
        "requested": {
            "width": arguments.width,
            "height": arguments.height,
            "fps": arguments.fps,
            "sample_count": arguments.sample_count,
        },
        "opened": bool(camera.isOpened()),
        "samples": [],
    }
    if not camera.isOpened():
        print(json.dumps(result, indent=2, sort_keys=True))
        raise SystemExit(2)

    result["reported_properties"] = {
        "width": camera.get(cv2.CAP_PROP_FRAME_WIDTH),
        "height": camera.get(cv2.CAP_PROP_FRAME_HEIGHT),
        "fps": camera.get(cv2.CAP_PROP_FPS),
        "fourcc": fourcc_text(camera.get(cv2.CAP_PROP_FOURCC)),
    }
    previous_arrival_ns = None
    intervals_ms = []
    failed_reads = 0
    try:
        for attempt in range(arguments.maximum_attempts):
            ok, frame = camera.read()
            arrival_ns = int(time.monotonic() * 1e9)
            if not ok or frame is None:
                failed_reads += 1
                continue
            if previous_arrival_ns is not None:
                intervals_ms.append((arrival_ns - previous_arrival_ns) / 1e6)
            previous_arrival_ns = arrival_ns
            channel_means = np.mean(frame, axis=(0, 1)).tolist()
            channel_standard_deviations = np.std(frame, axis=(0, 1)).tolist()
            result["samples"].append(
                {
                    "sample_index": len(result["samples"]),
                    "attempt_index": attempt,
                    "arrival_monotonic_ns": arrival_ns,
                    "shape": [int(value) for value in frame.shape],
                    "dtype": str(frame.dtype),
                    "minimum_pixel_value": int(frame.min()),
                    "maximum_pixel_value": int(frame.max()),
                    "channel_means_bgr": channel_means,
                    "channel_population_standard_deviations_bgr": channel_standard_deviations,
                }
            )
            if len(result["samples"]) >= arguments.sample_count:
                break
    finally:
        camera.release()

    result["failed_reads"] = failed_reads
    result["received_sample_count"] = len(result["samples"])
    result["complete"] = len(result["samples"]) >= arguments.sample_count
    result["arrival_interval_summary"] = summarize_intervals(intervals_ms)
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["complete"]:
        print("camera probe did not receive all requested frames", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
