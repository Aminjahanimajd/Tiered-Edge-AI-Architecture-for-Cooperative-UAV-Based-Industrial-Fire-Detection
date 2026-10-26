#!/usr/bin/env python3
"""Collect bounded ROS 2 Image metadata without preserving pixel content."""

from __future__ import print_function

import argparse
import json
import statistics
import sys
import time


def expected_payload_bytes(width, height, encoding):
    encoding = encoding.strip().lower()
    pixels = int(width) * int(height)
    if encoding in ("nv12", "nv21"):
        return pixels * 3 // 2
    if encoding in ("rgb8", "bgr8"):
        return pixels * 3
    if encoding in ("rgba8", "bgra8"):
        return pixels * 4
    if encoding in ("mono8", "8uc1"):
        return pixels
    if encoding in ("yuv422", "uyvy", "yuyv"):
        return pixels * 2
    return None


def summarize(samples, topic, requested_count, timeout_seconds):
    intervals_ms = []
    for previous, current in zip(samples, samples[1:]):
        intervals_ms.append(
            (current["arrival_monotonic_ns"] - previous["arrival_monotonic_ns"])
            / 1e6
        )
    unique_shapes = sorted(
        {
            (sample["width"], sample["height"], sample["encoding"], sample["step"])
            for sample in samples
        }
    )
    unique_payload_lengths = sorted({sample["data_length"] for sample in samples})
    expected_lengths = sorted(
        {
            expected_payload_bytes(
                sample["width"], sample["height"], sample["encoding"]
            )
            for sample in samples
            if expected_payload_bytes(
                sample["width"], sample["height"], sample["encoding"]
            )
            is not None
        }
    )
    payload_matches_encoding = None
    if expected_lengths:
        payload_matches_encoding = all(
            sample["data_length"]
            == expected_payload_bytes(
                sample["width"], sample["height"], sample["encoding"]
            )
            for sample in samples
        )
    interval_summary = None
    if intervals_ms:
        interval_summary = {
            "count": len(intervals_ms),
            "mean_ms": statistics.mean(intervals_ms),
            "median_ms": statistics.median(intervals_ms),
            "minimum_ms": min(intervals_ms),
            "maximum_ms": max(intervals_ms),
            "population_standard_deviation_ms": statistics.pstdev(intervals_ms),
        }
    return {
        "schema_version": 1,
        "probe_type": "ros_image_metadata_only",
        "pixel_content_persisted": False,
        "topic": topic,
        "requested_sample_count": requested_count,
        "received_sample_count": len(samples),
        "timeout_seconds": timeout_seconds,
        "complete": len(samples) >= requested_count,
        "unique_shapes": [
            {
                "width": shape[0],
                "height": shape[1],
                "encoding": shape[2],
                "step": shape[3],
            }
            for shape in unique_shapes
        ],
        "unique_payload_lengths": unique_payload_lengths,
        "encoding_implied_payload_lengths": expected_lengths,
        "payload_matches_encoding": payload_matches_encoding,
        "arrival_interval_summary": interval_summary,
        "samples": samples,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="/hires_small_color")
    parser.add_argument("--sample-count", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    arguments = parser.parse_args()
    if arguments.sample_count < 1:
        parser.error("--sample-count must be positive")
    if arguments.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")

    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image

    samples = []

    class MetadataProbe(Node):
        def __init__(self):
            Node.__init__(self, "drone_enhanced_image_metadata_probe")
            self.subscription = self.create_subscription(
                Image,
                arguments.topic,
                self.callback,
                qos_profile_sensor_data,
            )

        def callback(self, message):
            if len(samples) >= arguments.sample_count:
                return
            samples.append(
                {
                    "sample_index": len(samples),
                    "arrival_monotonic_ns": int(time.monotonic() * 1e9),
                    "header_stamp_sec": int(message.header.stamp.sec),
                    "header_stamp_nanosec": int(message.header.stamp.nanosec),
                    "frame_id": message.header.frame_id,
                    "height": int(message.height),
                    "width": int(message.width),
                    "encoding": message.encoding,
                    "is_bigendian": int(message.is_bigendian),
                    "step": int(message.step),
                    "data_length": len(message.data),
                }
            )

    rclpy.init()
    node = MetadataProbe()
    deadline = time.monotonic() + arguments.timeout_seconds
    try:
        while len(samples) < arguments.sample_count and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.25)
    finally:
        node.destroy_node()
        rclpy.shutdown()

    result = summarize(
        samples,
        arguments.topic,
        arguments.sample_count,
        arguments.timeout_seconds,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["complete"]:
        print("metadata probe timed out before receiving all samples", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
