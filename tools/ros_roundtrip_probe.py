#!/usr/bin/env python3
"""Measure correlated HazardAlert-to-HazardVerdict ROS 2 round trips."""

from __future__ import print_function

import argparse
import json
import math
import statistics
import time


def monotonic_ns():
    function = getattr(time, "monotonic_ns", None)
    if function is not None:
        return function()
    return int(time.monotonic() * 1000000000)


def percentile(values, percentage):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile requires values")
    position = (len(ordered) - 1) * float(percentage) / 100.0
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize_rtt_ms(values):
    values = [float(value) for value in values]
    if not values:
        return None
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
        "population_standard_deviation": statistics.pstdev(values),
        "p95": percentile(values, 95),
    }


def make_qos():
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

    qos = QoSProfile(depth=100)
    qos.reliability = ReliabilityPolicy.RELIABLE
    qos.durability = DurabilityPolicy.VOLATILE
    return qos


def populate_alert(message, node, experiment_id, trial_id, event_id):
    message.header.stamp = node.get_clock().now().to_msg()
    message.header.frame_id = "normalized_image_plane"
    message.experiment_id = experiment_id
    message.trial_id = trial_id
    message.event_id = event_id
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


def populate_verdict(message, alert, node):
    message.header.stamp = node.get_clock().now().to_msg()
    message.header.frame_id = "scout_injected_probe"
    message.experiment_id = alert.experiment_id
    message.trial_id = alert.trial_id
    message.event_id = alert.event_id
    message.source_device = "scout"
    message.verdict = "CONFIRMED"
    message.hazard_type = alert.hazard_type
    message.confidence = 0.75
    message.alert_received_monotonic_ns = monotonic_ns()
    message.source_frame_monotonic_ns = monotonic_ns()
    message.verdict_monotonic_ns = monotonic_ns()
    message.model_sha256 = "0" * 64
    message.reason = "camera_free_roundtrip_probe"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("initiator", "responder"))
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--event-prefix", required=True)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--per-event-timeout-seconds", type=float, default=1.0)
    parser.add_argument("--global-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--publisher-start-delay-seconds", type=float, default=3.0)
    arguments = parser.parse_args()
    if arguments.count <= 0:
        parser.error("--count must be positive")
    if min(arguments.per_event_timeout_seconds, arguments.global_timeout_seconds) <= 0:
        parser.error("timeouts must be positive")

    import rclpy
    from drone_enhanced_interfaces.msg import HazardAlert, HazardVerdict

    rclpy.init(args=None)
    node = rclpy.create_node(
        "camera_free_roundtrip_{}_{}".format(arguments.role, int(time.time()))
    )
    qos = make_qos()
    started_ns = monotonic_ns()
    try:
        if arguments.role == "initiator":
            received = {}
            unexpected = []

            def verdict_callback(message):
                if message.event_id.startswith(arguments.event_prefix + "-"):
                    if message.event_id not in received:
                        received[message.event_id] = {
                            "received_monotonic_ns": monotonic_ns(),
                            "verdict": message.verdict,
                            "source_device": message.source_device,
                        }
                else:
                    unexpected.append(message.event_id)

            subscription = node.create_subscription(
                HazardVerdict,
                "/swarm/hazard_verdict",
                verdict_callback,
                qos,
            )
            publisher = node.create_publisher(
                HazardAlert, "/swarm/hazard_alert", qos
            )
            if arguments.publisher_start_delay_seconds:
                time.sleep(arguments.publisher_start_delay_seconds)
            discovery_deadline = time.monotonic() + 20.0
            subscriber_count = node.count_subscribers("/swarm/hazard_alert")
            while subscriber_count < 1 and time.monotonic() < discovery_deadline:
                rclpy.spin_once(node, timeout_sec=0.1)
                subscriber_count = node.count_subscribers("/swarm/hazard_alert")
            if subscriber_count < 1:
                raise RuntimeError("roundtrip responder was not discovered")

            samples = []
            global_deadline = time.monotonic() + arguments.global_timeout_seconds
            for index in range(arguments.count):
                if time.monotonic() >= global_deadline:
                    break
                event_id = "{}-{:04d}".format(arguments.event_prefix, index)
                message = HazardAlert()
                populate_alert(
                    message,
                    node,
                    arguments.experiment_id,
                    arguments.trial_id,
                    event_id,
                )
                sent_ns = monotonic_ns()
                publisher.publish(message)
                event_deadline = min(
                    global_deadline,
                    time.monotonic() + arguments.per_event_timeout_seconds,
                )
                while event_id not in received and time.monotonic() < event_deadline:
                    rclpy.spin_once(node, timeout_sec=0.01)
                reply = received.get(event_id)
                sample = {
                    "sequence": index,
                    "event_id": event_id,
                    "sent_monotonic_ns": sent_ns,
                    "received": reply is not None,
                }
                if reply is not None:
                    sample.update(reply)
                    sample["round_trip_ms"] = (
                        reply["received_monotonic_ns"] - sent_ns
                    ) / 1000000.0
                    sample["correlation_match"] = (
                        reply["verdict"] == "CONFIRMED"
                        and reply["source_device"] == "scout"
                    )
                samples.append(sample)
            rtts = [sample["round_trip_ms"] for sample in samples if sample["received"]]
            mismatched = [
                sample["event_id"]
                for sample in samples
                if sample["received"] and not sample["correlation_match"]
            ]
            result = {
                "status": "COMPLETE",
                "role": "initiator",
                "experiment_id": arguments.experiment_id,
                "trial_id": arguments.trial_id,
                "event_prefix": arguments.event_prefix,
                "requested_count": arguments.count,
                "attempted_count": len(samples),
                "received_count": len(rtts),
                "missing_count": len(samples) - len(rtts),
                "observed_reply_fraction": (
                    float(len(rtts)) / len(samples) if samples else 0.0
                ),
                "mismatched_event_ids": mismatched,
                "unexpected_event_ids": unexpected,
                "subscriber_count_at_start": subscriber_count,
                "rtt_summary_ms": summarize_rtt_ms(rtts),
                "samples": samples,
                "started_monotonic_ns": started_ns,
                "finished_monotonic_ns": monotonic_ns(),
                "one_way_latency_claim_permitted": False,
                "round_trip_scope": "ROS2 alert publish to correlated verdict callback",
            }
            print(json.dumps(result, sort_keys=True))
            del subscription
        else:
            publisher = node.create_publisher(
                HazardVerdict, "/swarm/hazard_verdict", qos
            )
            received_ids = []
            duplicate_ids = []
            seen = set()

            def alert_callback(message):
                if not message.event_id.startswith(arguments.event_prefix + "-"):
                    return
                if message.event_id in seen:
                    duplicate_ids.append(message.event_id)
                    return
                seen.add(message.event_id)
                received_ids.append(message.event_id)
                verdict = HazardVerdict()
                populate_verdict(verdict, message, node)
                publisher.publish(verdict)

            subscription = node.create_subscription(
                HazardAlert, "/swarm/hazard_alert", alert_callback, qos
            )
            deadline = time.monotonic() + arguments.global_timeout_seconds
            while len(received_ids) < arguments.count and time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.05)
            # Keep the participant alive briefly for the final reliable reply.
            for unused in range(10):
                rclpy.spin_once(node, timeout_sec=0.05)
            print(
                json.dumps(
                    {
                        "status": "COMPLETE",
                        "role": "responder",
                        "experiment_id": arguments.experiment_id,
                        "trial_id": arguments.trial_id,
                        "event_prefix": arguments.event_prefix,
                        "expected_count": arguments.count,
                        "received_count": len(received_ids),
                        "duplicate_event_ids": duplicate_ids,
                        "received_event_ids": received_ids,
                        "started_monotonic_ns": started_ns,
                        "finished_monotonic_ns": monotonic_ns(),
                        "one_way_latency_claim_permitted": False,
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
