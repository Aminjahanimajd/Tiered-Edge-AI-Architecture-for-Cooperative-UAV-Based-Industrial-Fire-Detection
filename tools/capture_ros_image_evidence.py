#!/usr/bin/env python3
"""Capture one ROS Image as a lossless PNG plus a hashed evidence record.

The tool is intentionally read-only with respect to the camera and vehicle. It
subscribes to one image topic, validates the payload geometry, writes the first
accepted frame, and records enough metadata to trace the visual evidence back
to the ROS message. No flight-control topics are opened.
"""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import time


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="/tracking")
    parser.add_argument("--output", required=True)
    parser.add_argument("--metadata-output", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    arguments = parser.parse_args()
    if os.path.exists(arguments.output) or os.path.exists(arguments.metadata_output):
        parser.error("output exists; visual evidence capture is non-overwriting")

    import cv2
    import numpy as np
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image

    class Capture(Node):
        def __init__(self):
            super(Capture, self).__init__("visual_evidence_capture")
            self.result = None
            self.subscription = self.create_subscription(
                Image, arguments.topic, self.callback, qos_profile_sensor_data
            )

        def callback(self, message):
            if self.result is not None:
                return
            width = int(message.width)
            height = int(message.height)
            step = int(message.step)
            encoding = str(message.encoding).strip().lower()
            raw = np.frombuffer(message.data, dtype=np.uint8)
            if encoding not in ("mono8", "8uc1"):
                raise ValueError("capture currently requires mono8; received {}".format(encoding))
            if raw.size != width * height or step not in (0, width):
                raise ValueError("invalid mono8 geometry")
            gray = raw.reshape((height, width))
            output_parent = os.path.dirname(os.path.abspath(arguments.output))
            if output_parent and not os.path.isdir(output_parent):
                os.makedirs(output_parent)
            if not cv2.imwrite(arguments.output, gray, [int(cv2.IMWRITE_PNG_COMPRESSION), 3]):
                raise RuntimeError("PNG write failed")
            now_ns = time.monotonic_ns() if hasattr(time, "monotonic_ns") else int(time.monotonic() * 1000000000)
            self.result = {
                "schema_version": 1,
                "evidence_type": "physical_camera_visual_evidence",
                "claim_boundary": "One stationary Scout camera frame; not flight, localization, detection-accuracy, or industrial-site evidence.",
                "topic": arguments.topic,
                "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "capture_monotonic_ns": int(now_ns),
                "header_stamp_sec": int(message.header.stamp.sec),
                "header_stamp_nanosec": int(message.header.stamp.nanosec),
                "header_frame_id": str(message.header.frame_id),
                "width": width,
                "height": height,
                "step": step,
                "encoding": encoding,
                "data_length": int(raw.size),
                "minimum": int(raw.min()),
                "maximum": int(raw.max()),
                "mean": float(raw.mean()),
                "output_path": os.path.abspath(arguments.output),
            }

    rclpy.init()
    node = Capture()
    deadline = time.monotonic() + arguments.timeout_seconds
    try:
        while node.result is None and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.5)
        if node.result is None:
            raise TimeoutError("no compatible frame received before timeout")
        node.result["png_sha256"] = sha256_file(arguments.output)
        node.result["status"] = "PASS"
        with open(arguments.metadata_output, "x") as destination:
            json.dump(node.result, destination, indent=2, sort_keys=True)
            destination.write("\n")
        print(json.dumps(node.result, sort_keys=True))
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
