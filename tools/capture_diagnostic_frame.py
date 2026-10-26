#!/usr/bin/env python3
"""Capture exactly one diagnostic frame and report its identity and geometry."""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import time


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save(frame, output, source_metadata):
    import cv2

    output = os.path.abspath(output)
    if os.path.exists(output):
        raise RuntimeError("diagnostic output already exists")
    parent = os.path.dirname(output)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if not cv2.imwrite(output, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95]):
        raise RuntimeError("OpenCV failed to write diagnostic frame")
    result = {
        "status": "PASS",
        "output": output,
        "sha256": sha256_file(output),
        "size_bytes": os.path.getsize(output),
        "shape": [int(value) for value in frame.shape],
        "dtype": str(frame.dtype),
        "source_metadata": source_metadata,
        "diagnostic_image_persisted": True,
    }
    print(json.dumps(result, sort_keys=True))


def capture_opencv(args):
    import cv2

    pipeline = (
        "v4l2src device={0} ! video/x-raw, format=YUY2, width=640, "
        "height=480, framerate=30/1 ! videoconvert ! video/x-raw, "
        "format=BGR ! appsink drop=true max-buffers=1 sync=false"
    ).format(args.device)
    camera = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    if not camera.isOpened():
        raise RuntimeError("camera did not open")
    try:
        ok, frame = camera.read()
    finally:
        camera.release()
    if not ok or frame is None:
        raise RuntimeError("camera read failed")
    save(frame, args.output, {"mode": "opencv_gstreamer", "pipeline": pipeline})


def capture_ros(args):
    import rclpy
    from drone_enhanced_nodes.runtime_support import decode_ros_image_to_bgr
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image

    received = []

    class CaptureNode(Node):
        def __init__(self):
            Node.__init__(self, "diagnostic_frame_capture")
            self.subscription = self.create_subscription(
                Image, args.topic, self.callback, qos_profile_sensor_data
            )

        def callback(self, message):
            if received:
                return
            frame, metadata = decode_ros_image_to_bgr(message, "nv21")
            received.append((frame, metadata))

    rclpy.init()
    node = CaptureNode()
    deadline = time.monotonic() + args.timeout_seconds
    try:
        while not received and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.25)
    finally:
        node.destroy_node()
        rclpy.shutdown()
    if not received:
        raise RuntimeError("ROS image timeout")
    save(received[0][0], args.output, dict(received[0][1], mode="ros_image"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("opencv", "ros"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="/dev/video2")
    parser.add_argument("--topic", default="/hires_small_color")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    args = parser.parse_args()
    if args.mode == "opencv":
        capture_opencv(args)
    else:
        capture_ros(args)


if __name__ == "__main__":
    main()
