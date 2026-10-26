#!/usr/bin/env python3
"""Publish one injected alert and await the live Scout node's verdict."""

from __future__ import print_function

import argparse
import json
import time


def monotonic_ns():
    function = getattr(time, "monotonic_ns", None)
    return function() if function is not None else int(time.monotonic() * 1000000000)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()

    import rclpy
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from drone_enhanced_interfaces.msg import HazardAlert, HazardVerdict

    qos = QoSProfile(depth=10)
    qos.reliability = ReliabilityPolicy.RELIABLE
    qos.durability = DurabilityPolicy.VOLATILE
    rclpy.init(args=None)
    node = rclpy.create_node("injected_live_hierarchy_probe")
    verdicts = []
    unrelated = []

    def verdict_callback(message):
        if message.event_id == args.event_id and not verdicts:
            verdicts.append((message, monotonic_ns()))
        elif message.event_id != args.event_id:
            unrelated.append(message.event_id)

    subscription = node.create_subscription(
        HazardVerdict, "/swarm/hazard_verdict", verdict_callback, qos
    )
    publisher = node.create_publisher(HazardAlert, "/swarm/hazard_alert", qos)
    try:
        discovery_deadline = time.monotonic() + min(args.timeout_seconds, 20.0)
        subscriber_count = node.count_subscribers("/swarm/hazard_alert")
        while subscriber_count < 1 and time.monotonic() < discovery_deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            subscriber_count = node.count_subscribers("/swarm/hazard_alert")
        if subscriber_count < 1:
            raise RuntimeError("live Scout alert subscriber was not discovered")

        message = HazardAlert()
        message.header.stamp = node.get_clock().now().to_msg()
        message.header.frame_id = "normalized_image_plane"
        message.experiment_id = args.experiment_id
        message.trial_id = args.trial_id
        message.event_id = args.event_id
        message.source_device = "sentinel"
        message.hazard_type = "fire"
        message.confidence = 0.75
        message.temporal_count = 3
        message.source_frame_monotonic_ns = monotonic_ns()
        message.alert_monotonic_ns = monotonic_ns()
        message.model_sha256 = "0" * 64
        message.target_u = 0.5
        message.target_v = 0.5
        message.bbox_width = 0.1
        message.bbox_height = 0.1
        message.frame_width = 640
        message.frame_height = 480
        published_ns = monotonic_ns()
        publisher.publish(message)

        deadline = time.monotonic() + args.timeout_seconds
        while not verdicts and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
        if not verdicts:
            raise RuntimeError("live Scout verdict was not received before timeout")
        verdict, received_ns = verdicts[0]
        expected = {
            "experiment_id": args.experiment_id,
            "trial_id": args.trial_id,
            "event_id": args.event_id,
            "source_device": "scout",
            "hazard_type": "fire",
        }
        observed = {
            "experiment_id": verdict.experiment_id,
            "trial_id": verdict.trial_id,
            "event_id": verdict.event_id,
            "source_device": verdict.source_device,
            "hazard_type": verdict.hazard_type,
            "verdict": verdict.verdict,
            "confidence": float(verdict.confidence),
            "reason": verdict.reason,
            "model_sha256": verdict.model_sha256,
            "alert_received_monotonic_ns": int(verdict.alert_received_monotonic_ns),
            "source_frame_monotonic_ns": int(verdict.source_frame_monotonic_ns),
            "verdict_monotonic_ns": int(verdict.verdict_monotonic_ns),
        }
        mismatches = {
            key: {"expected": value, "observed": observed.get(key)}
            for key, value in expected.items()
            if observed.get(key) != value
        }
        if mismatches:
            raise RuntimeError("correlation-field mismatch: {}".format(mismatches))
        result = {
            "schema_version": 1,
            "status": "PASS",
            "probe_type": "injected_alert_to_live_scout_camera_inference_verdict",
            "subscriber_count_at_publish": subscriber_count,
            "published_monotonic_ns": published_ns,
            "received_monotonic_ns": received_ns,
            "injected_alert_to_verdict_callback_ms": (received_ns - published_ns) / 1000000.0,
            "observed_verdict": observed,
            "unrelated_event_ids": unrelated,
            "claim_boundary": (
                "Latency begins at an injected alert and includes DDS transport, Scout queueing, "
                "current-frame TFLite inference, and verdict transport. It excludes Sentinel "
                "camera inference and is not ignition-to-detection latency."
            ),
        }
        print(json.dumps(result, sort_keys=True))
    finally:
        del subscription
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
