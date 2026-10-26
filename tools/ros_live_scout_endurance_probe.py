#!/usr/bin/env python3
"""Drive repeated, correlated Scout camera inferences without actuation."""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path


def monotonic_ns():
    function = getattr(time, "monotonic_ns", None)
    return function() if function is not None else int(time.monotonic() * 1000000000)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256(path):
    digest = hashlib.sha256()
    with open(str(path), "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=float, default=1800.0)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    parser.add_argument("--verdict-timeout-seconds", type=float, default=3.0)
    args = parser.parse_args()
    if args.output_directory.exists():
        parser.error("output directory exists; probe is non-overwriting")
    if args.duration_seconds < 60 or args.interval_seconds <= 0 or args.verdict_timeout_seconds <= 0:
        parser.error("invalid duration/interval")
    args.output_directory.mkdir(parents=True)
    events_path = args.output_directory / "probe_events.jsonl"

    import rclpy
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from drone_enhanced_interfaces.msg import HazardAlert, HazardVerdict

    qos = QoSProfile(depth=10)
    qos.reliability = ReliabilityPolicy.RELIABLE
    qos.durability = DurabilityPolicy.VOLATILE
    rclpy.init(args=None)
    node = rclpy.create_node("live_scout_endurance_probe")
    received = {}
    duplicates = []
    unexpected = []
    expected_ids = set()

    def callback(message):
        received_ns = monotonic_ns()
        if message.event_id not in expected_ids:
            unexpected.append(message.event_id)
        elif message.event_id in received:
            duplicates.append(message.event_id)
        else:
            received[message.event_id] = (message, received_ns)

    subscription = node.create_subscription(HazardVerdict, "/swarm/hazard_verdict", callback, qos)
    publisher = node.create_publisher(HazardAlert, "/swarm/hazard_alert", qos)
    start_utc = utc_now()
    start = time.monotonic()
    records = []
    sequence = 0
    try:
        discovery_deadline = time.monotonic() + 30.0
        while node.count_subscribers("/swarm/hazard_alert") < 1 and time.monotonic() < discovery_deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
        if node.count_subscribers("/swarm/hazard_alert") < 1:
            raise RuntimeError("Scout alert subscriber was not discovered")

        with events_path.open("x", encoding="utf-8") as destination:
            while time.monotonic() - start < args.duration_seconds:
                cycle_started = time.monotonic()
                event_id = "{}-{:06d}".format(args.trial_id, sequence)
                expected_ids.add(event_id)
                message = HazardAlert()
                message.header.stamp = node.get_clock().now().to_msg()
                message.header.frame_id = "normalized_image_plane"
                message.experiment_id = args.experiment_id
                message.trial_id = args.trial_id
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
                sent_ns = monotonic_ns()
                publisher.publish(message)
                deadline = time.monotonic() + args.verdict_timeout_seconds
                while event_id not in received and time.monotonic() < deadline:
                    rclpy.spin_once(node, timeout_sec=0.05)
                if event_id in received:
                    verdict, received_ns = received[event_id]
                    correlation = (
                        verdict.experiment_id == args.experiment_id
                        and verdict.trial_id == args.trial_id
                        and verdict.event_id == event_id
                        and verdict.source_device == "scout"
                    )
                    record = {
                        "sequence": sequence,
                        "event_id": event_id,
                        "sent_monotonic_ns": sent_ns,
                        "received_monotonic_ns": received_ns,
                        "latency_ms": (received_ns - sent_ns) / 1000000.0,
                        "received": True,
                        "correlation_match": correlation,
                        "verdict": verdict.verdict,
                        "confidence": float(verdict.confidence),
                        "reason": verdict.reason,
                    }
                else:
                    record = {"sequence": sequence, "event_id": event_id, "sent_monotonic_ns": sent_ns, "received": False, "correlation_match": False}
                records.append(record)
                destination.write(json.dumps(record, sort_keys=True) + "\n")
                destination.flush()
                sequence += 1
                remaining = args.interval_seconds - (time.monotonic() - cycle_started)
                while remaining > 0 and time.monotonic() - start < args.duration_seconds:
                    rclpy.spin_once(node, timeout_sec=min(0.1, remaining))
                    remaining = args.interval_seconds - (time.monotonic() - cycle_started)
    finally:
        del subscription
        node.destroy_node()
        rclpy.shutdown()

    successful = [record for record in records if record["received"]]
    latencies = [record["latency_ms"] for record in successful]
    mismatches = [record for record in successful if not record["correlation_match"]]
    summary = {
        "schema_version": 1,
        "status": "PASS" if records and len(successful) == len(records) and not mismatches and not duplicates else "FAIL",
        "probe_type": "periodic_injected_alert_to_live_scout_camera_inference_verdict",
        "experiment_id": args.experiment_id,
        "trial_id": args.trial_id,
        "started_utc": start_utc,
        "finished_utc": utc_now(),
        "duration_seconds": time.monotonic() - start,
        "interval_seconds": args.interval_seconds,
        "verdict_timeout_seconds": args.verdict_timeout_seconds,
        "requested_count": len(records),
        "received_count": len(successful),
        "missing_count": len(records) - len(successful),
        "correlation_mismatch_count": len(mismatches),
        "duplicate_count": len(duplicates),
        "unexpected_count": len(unexpected),
        "latency_ms": {
            "n": len(latencies),
            "mean": statistics.mean(latencies) if latencies else None,
            "median": statistics.median(latencies) if latencies else None,
            "minimum": min(latencies) if latencies else None,
            "maximum": max(latencies) if latencies else None,
            "p95": percentile(latencies, 0.95) if latencies else None,
            "population_standard_deviation": statistics.pstdev(latencies) if latencies else None,
        },
        "events_sha256": sha256(events_path),
        "claim_boundary": "Latency begins at a synthetic ROS alert and includes network transport, Scout queueing, current-frame inference, and verdict transport. It excludes Sentinel detection and is not ignition-to-detection latency.",
        "safety_state": "stationary; propellers removed; publisher/subscriber only; no vehicle command",
    }
    summary_path = args.output_directory / "probe_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    if summary["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
