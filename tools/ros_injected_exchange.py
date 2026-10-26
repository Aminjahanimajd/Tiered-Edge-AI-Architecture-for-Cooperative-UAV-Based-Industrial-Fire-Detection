#!/usr/bin/env python3
"""Publish or receive one correlated enhanced ROS message without a camera."""

from __future__ import print_function

import argparse
import json
import time


def monotonic_ns():
    function = getattr(time, "monotonic_ns", None)
    if function is not None:
        return function()
    return int(time.monotonic() * 1000000000)


def message_class_and_topic(message_type):
    from drone_enhanced_interfaces.msg import HazardAlert, HazardVerdict

    if message_type == "alert":
        return HazardAlert, "/swarm/hazard_alert"
    if message_type == "verdict":
        return HazardVerdict, "/swarm/hazard_verdict"
    raise ValueError("unsupported message type: {}".format(message_type))


def populate_message(message, message_type, arguments, node):
    message.header.stamp = node.get_clock().now().to_msg()
    message.header.frame_id = "normalized_image_plane"
    message.experiment_id = arguments.experiment_id
    message.trial_id = arguments.trial_id
    message.event_id = arguments.event_id
    message.source_device = arguments.source_device
    message.hazard_type = "fire"
    message.confidence = 0.75
    message.source_frame_monotonic_ns = monotonic_ns()
    message.model_sha256 = "0" * 64
    if message_type == "alert":
        message.temporal_count = 3
        message.alert_monotonic_ns = monotonic_ns()
        message.target_u = 0.5
        message.target_v = 0.5
        message.bbox_width = 0.1
        message.bbox_height = 0.1
        message.frame_width = 640
        message.frame_height = 480
    else:
        message.verdict = "CONFIRMED"
        message.alert_received_monotonic_ns = monotonic_ns()
        message.verdict_monotonic_ns = monotonic_ns()
        message.reason = "camera_free_injected_transport_check"


def message_identity(message):
    values = {
        "experiment_id": message.experiment_id,
        "trial_id": message.trial_id,
        "event_id": message.event_id,
        "source_device": message.source_device,
        "hazard_type": message.hazard_type,
        "confidence": float(message.confidence),
        "source_frame_monotonic_ns": int(message.source_frame_monotonic_ns),
        "model_sha256": message.model_sha256,
    }
    if hasattr(message, "verdict"):
        values["verdict"] = message.verdict
        values["reason"] = message.reason
    else:
        values["temporal_count"] = int(message.temporal_count)
        values["target_u"] = float(message.target_u)
        values["target_v"] = float(message.target_v)
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("publisher", "subscriber"))
    parser.add_argument("message_type", choices=("alert", "verdict"))
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--source-device", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--publisher-start-delay-seconds", type=float, default=2.0)
    arguments = parser.parse_args()
    if arguments.timeout_seconds <= 0.0:
        parser.error("--timeout-seconds must be positive")
    if arguments.publisher_start_delay_seconds < 0.0:
        parser.error("--publisher-start-delay-seconds cannot be negative")

    import rclpy
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

    message_class, topic = message_class_and_topic(arguments.message_type)
    qos = QoSProfile(depth=10)
    qos.reliability = ReliabilityPolicy.RELIABLE
    qos.durability = DurabilityPolicy.VOLATILE
    rclpy.init(args=None)
    node = rclpy.create_node(
        "injected_{}_{}_{}".format(
            arguments.message_type, arguments.role, int(time.time())
        )
    )
    started_ns = monotonic_ns()
    try:
        if arguments.role == "publisher":
            publisher = node.create_publisher(message_class, topic, qos)
            if arguments.publisher_start_delay_seconds:
                time.sleep(arguments.publisher_start_delay_seconds)
            deadline = time.monotonic() + arguments.timeout_seconds
            subscriber_count = node.count_subscribers(topic)
            while subscriber_count < 1 and time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.1)
                subscriber_count = node.count_subscribers(topic)
            if subscriber_count < 1:
                raise RuntimeError("no subscriber discovered before timeout")
            message = message_class()
            populate_message(message, arguments.message_type, arguments, node)
            published_ns = monotonic_ns()
            publisher.publish(message)
            for unused in range(10):
                rclpy.spin_once(node, timeout_sec=0.1)
            print(
                json.dumps(
                    {
                        "status": "PASS",
                        "role": "publisher",
                        "message_type": arguments.message_type,
                        "topic": topic,
                        "subscriber_count": subscriber_count,
                        "started_monotonic_ns": started_ns,
                        "published_monotonic_ns": published_ns,
                        "message": message_identity(message),
                        "latency_claim_permitted": False,
                    },
                    sort_keys=True,
                )
            )
        else:
            received = []
            unexpected_events = []

            def callback(message):
                if message.event_id == arguments.event_id:
                    if not received:
                        received.append((message, monotonic_ns()))
                else:
                    unexpected_events.append(message.event_id)

            subscription = node.create_subscription(
                message_class, topic, callback, qos
            )
            deadline = time.monotonic() + arguments.timeout_seconds
            while not received and time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.1)
            if not received:
                raise RuntimeError("expected event was not received before timeout")
            message, received_ns = received[0]
            expected = {
                "experiment_id": arguments.experiment_id,
                "trial_id": arguments.trial_id,
                "event_id": arguments.event_id,
                "source_device": arguments.source_device,
            }
            observed = message_identity(message)
            mismatches = {
                key: {"expected": value, "observed": observed.get(key)}
                for key, value in expected.items()
                if observed.get(key) != value
            }
            if mismatches:
                raise RuntimeError("correlation-field mismatch: {}".format(mismatches))
            print(
                json.dumps(
                    {
                        "status": "PASS",
                        "role": "subscriber",
                        "message_type": arguments.message_type,
                        "topic": topic,
                        "started_monotonic_ns": started_ns,
                        "received_monotonic_ns": received_ns,
                        "unexpected_event_ids": unexpected_events,
                        "message": observed,
                        "correlation_fields_match": True,
                        "latency_claim_permitted": False,
                    },
                    sort_keys=True,
                )
            )
            del subscription
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
