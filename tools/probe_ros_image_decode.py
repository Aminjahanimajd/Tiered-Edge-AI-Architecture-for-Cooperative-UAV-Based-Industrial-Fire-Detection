#!/usr/bin/env python3
"""Exercise the enhanced ROS image decoder on live messages without saving images."""

from __future__ import print_function

import argparse
import json
import sys
import time


def decoded_sample(message, frame, metadata, sample_index, arrival_ns):
    import numpy as np

    return {
        "sample_index": int(sample_index),
        "arrival_monotonic_ns": int(arrival_ns),
        "header_stamp_sec": int(message.header.stamp.sec),
        "header_stamp_nanosec": int(message.header.stamp.nanosec),
        "frame_id": message.header.frame_id,
        "source_metadata": dict(metadata),
        "bgr_shape": [int(value) for value in frame.shape],
        "bgr_dtype": str(frame.dtype),
        "minimum_pixel_value": int(frame.min()),
        "maximum_pixel_value": int(frame.max()),
        "channel_means_bgr": np.mean(frame, axis=(0, 1)).tolist(),
        "channel_population_standard_deviations_bgr": np.std(
            frame, axis=(0, 1)
        ).tolist(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="/hires_small_color")
    parser.add_argument("--sample-count", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--yuv420-format", choices=("nv12", "nv21"), default="nv21")
    arguments = parser.parse_args()
    if arguments.sample_count < 1:
        parser.error("--sample-count must be positive")
    if arguments.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")

    import rclpy
    from drone_enhanced_nodes.runtime_support import decode_ros_image_to_bgr
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image

    samples = []
    errors = []

    class DecodeProbe(Node):
        def __init__(self):
            Node.__init__(self, "drone_enhanced_image_decode_probe")
            self.subscription = self.create_subscription(
                Image, arguments.topic, self.callback, qos_profile_sensor_data
            )

        def callback(self, message):
            if len(samples) >= arguments.sample_count:
                return
            arrival_ns = int(time.monotonic() * 1e9)
            try:
                frame, metadata = decode_ros_image_to_bgr(
                    message, arguments.yuv420_format
                )
                samples.append(
                    decoded_sample(
                        message, frame, metadata, len(samples), arrival_ns
                    )
                )
            except Exception as exc:
                errors.append(
                    {
                        "arrival_monotonic_ns": arrival_ns,
                        "error_type": type(exc).__name__,
                        "reason": str(exc),
                    }
                )

    rclpy.init()
    node = DecodeProbe()
    deadline = time.monotonic() + arguments.timeout_seconds
    try:
        while len(samples) < arguments.sample_count and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.25)
    finally:
        node.destroy_node()
        rclpy.shutdown()

    result = {
        "schema_version": 1,
        "probe_type": "enhanced_ros_image_decode_statistics",
        "pixel_content_persisted": False,
        "topic": arguments.topic,
        "requested_sample_count": arguments.sample_count,
        "received_and_decoded_sample_count": len(samples),
        "decode_error_count": len(errors),
        "complete": len(samples) >= arguments.sample_count,
        "samples": samples,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["complete"] or errors:
        print("live decoder probe did not complete cleanly", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
