#!/usr/bin/env python3
"""Validate repeated Scout no-frame fail-closed evidence."""

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


def last_json(path: Path) -> dict:
    for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise ValueError(f"no JSON record in {path}")


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-directory", type=Path, required=True)
    parser.add_argument("--scout-events", type=Path, required=True)
    parser.add_argument("--scout-manifest", type=Path, required=True)
    parser.add_argument("--node-exit-code", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; analysis is non-overwriting")

    probe_paths = sorted(args.probe_directory.glob("*.jsonl"))
    if len(probe_paths) != args.expected_count:
        raise ValueError(f"expected {args.expected_count} probes; found {len(probe_paths)}")
    probes = [last_json(path) for path in probe_paths]
    events = [
        json.loads(line)
        for line in args.scout_events.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    manifest = json.loads(args.scout_manifest.read_text(encoding="utf-8"))
    alerts = [row for row in events if row.get("event_type") == "hazard_alert_received"]
    verdicts = [row for row in events if row.get("event_type") == "hazard_verdict_published"]
    inferences = [row for row in events if row.get("event_type") == "verification_inference"]
    if len(alerts) != args.expected_count or len(verdicts) != args.expected_count:
        raise ValueError("Scout alert/verdict counts do not match expected repetitions")

    probe_ids = {row["observed_verdict"]["event_id"] for row in probes}
    alert_ids = {row["event_id"] for row in alerts}
    verdict_ids = {row["event_id"] for row in verdicts}
    if not (probe_ids == alert_ids == verdict_ids) or len(probe_ids) != args.expected_count:
        raise ValueError("event identity mismatch across probe and Scout records")
    for row in probes:
        observed = row["observed_verdict"]
        if row.get("status") != "PASS" or observed.get("verdict") != "ERROR":
            raise ValueError("probe did not receive a correlated ERROR verdict")
        if observed.get("reason") != "no_frame":
            raise ValueError(f"unexpected fault reason: {observed.get('reason')}")
        if observed.get("model_sha256") != manifest.get("model_sha256"):
            raise ValueError("probe/manifest model hash mismatch")
    if any(row.get("verdict") != "ERROR" or row.get("reason") != "no_frame" for row in verdicts):
        raise ValueError("Scout verdict log contains a non-no-frame outcome")
    if inferences:
        raise ValueError("verification inference occurred despite unavailable camera frames")

    exit_code = int(args.node_exit_code.read_text(encoding="utf-8").strip())
    if exit_code not in (0, 124, 130):
        raise ValueError(f"unexpected bounded node exit code: {exit_code}")
    latencies = [float(row["injected_alert_to_verdict_callback_ms"]) for row in probes]
    summary = {
        "schema_version": 1,
        "status": "PASS",
        "fault": "scout_ros_camera_interface_unavailable",
        "expected_repetitions": args.expected_count,
        "correlated_error_verdicts": len(probes),
        "reason": "no_frame",
        "verification_inference_count": 0,
        "unique_event_ids": len(probe_ids),
        "node_exit_code": exit_code,
        "latency_ms": {
            "n": len(latencies),
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
            "minimum": min(latencies),
            "maximum": max(latencies),
            "p95": percentile(latencies, 0.95),
            "population_standard_deviation": statistics.pstdev(latencies),
        },
        "raw_evidence": {
            "probe_files": [
                {"path": str(path.resolve()), "sha256": sha256(path)}
                for path in probe_paths
            ],
            "scout_events": {
                "path": str(args.scout_events.resolve()),
                "sha256": sha256(args.scout_events),
            },
            "scout_manifest": {
                "path": str(args.scout_manifest.resolve()),
                "sha256": sha256(args.scout_manifest),
            },
        },
        "claim_boundary": (
            "Five stationary injected-alert repetitions with the Scout ROS camera bridge "
            "intentionally absent. This demonstrates fail-closed no-frame handling at the "
            "ROS camera-interface boundary, not physical camera-hardware failure, flight, "
            "or industrial reliability."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
