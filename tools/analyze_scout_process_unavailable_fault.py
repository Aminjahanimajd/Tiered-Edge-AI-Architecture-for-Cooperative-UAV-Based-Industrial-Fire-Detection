#!/usr/bin/env python3
"""Validate the physical-device Scout-process-unavailable timeout evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sentinel-trial-directory", type=Path, required=True)
    parser.add_argument("--scout-snapshot-directory", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; analysis is non-overwriting")

    sentinel = args.sentinel_trial_directory
    scout = args.scout_snapshot_directory
    probe_path = sentinel / "probe_summary.json"
    event_paths = list((sentinel / "node_logs").rglob("events.jsonl"))
    manifest_paths = list((sentinel / "node_logs").rglob("session_manifest.json"))
    if len(event_paths) != 1 or len(manifest_paths) != 1:
        raise ValueError("expected exactly one Sentinel event log and manifest")
    events_path = event_paths[0]
    manifest_path = manifest_paths[0]
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    alerts = [row for row in events if row.get("event_type") == "hazard_alert_published"]
    decisions = [row for row in events if row.get("event_type") == "final_decision"]
    verdicts = [row for row in events if row.get("event_type") == "verdict_received"]
    if probe.get("status") != "PASS" or probe.get("repetitions") != args.expected_count:
        raise ValueError("fault harness did not report the expected PASS repetitions")
    if len(alerts) != args.expected_count or len(decisions) != args.expected_count or verdicts:
        raise ValueError("Sentinel event counts do not match unavailable-Scout behavior")
    ids = [{row["event_id"] for row in alerts}, {row["event_id"] for row in decisions}, {row["event_id"] for row in probe["samples"]}]
    if not (ids[0] == ids[1] == ids[2]) or len(ids[0]) != args.expected_count:
        raise ValueError("event IDs are not uniquely correlated")
    if any(row.get("decision") != "TIMEOUT" or row.get("reason") != "Scout response timeout" for row in decisions):
        raise ValueError("unexpected final decision in unavailable-Scout evidence")
    process_text = (scout / "scout_process_matches.txt").read_text(encoding="utf-8")
    node_text = (scout / "ros2_nodes_domain85.txt").read_text(encoding="utf-8")
    if "no matching Scout verification process" not in process_text or "scout_enhanced" in node_text:
        raise ValueError("Scout process absence was not demonstrated")
    latencies = [float(row["alert_to_decision_ms"]) for row in probe["samples"]]
    summary = {
        "schema_version": 1,
        "status": "PASS",
        "fault": "scout_verification_process_unavailable",
        "repetitions": args.expected_count,
        "correlated_timeout_decisions": len(decisions),
        "observed_scout_verdicts": len(verdicts),
        "configured_timeout_ms": float(probe["sentinel_timeout_ms_configured"]),
        "latency_ms": {
            "n": len(latencies),
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
            "minimum": min(latencies),
            "maximum": max(latencies),
            "p95": percentile(latencies, 0.95),
            "population_standard_deviation": statistics.pstdev(latencies),
        },
        "model_sha256": manifest["model_sha256"],
        "raw_evidence": {
            "probe_summary": {"path": str(probe_path.resolve()), "sha256": sha256(probe_path)},
            "sentinel_events": {"path": str(events_path.resolve()), "sha256": sha256(events_path)},
            "sentinel_manifest": {"path": str(manifest_path.resolve()), "sha256": sha256(manifest_path)},
            "scout_process_snapshot": {"path": str((scout / "processes.txt").resolve()), "sha256": sha256(scout / "processes.txt")},
            "scout_ros_nodes": {"path": str((scout / "ros2_nodes_domain85.txt").resolve()), "sha256": sha256(scout / "ros2_nodes_domain85.txt")},
        },
        "claim_boundary": (
            "Five synthetic detections were injected at the exact deployed Sentinel node's "
            "dispatch boundary while device-side process and ROS graph snapshots showed no Scout "
            "verification node. This tests Sentinel timeout handling, not camera detection, "
            "network disconnection, flight, or industrial reliability."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
