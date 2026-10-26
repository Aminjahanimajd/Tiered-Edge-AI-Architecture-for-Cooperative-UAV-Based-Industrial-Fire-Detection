#!/usr/bin/env python3
"""Validate delayed and duplicate Scout-verdict rejection evidence."""

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
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sentinel-trial-directory", type=Path, required=True)
    parser.add_argument("--scout-snapshot-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; analysis is non-overwriting")
    trial = args.sentinel_trial_directory
    probe_path = trial / "probe_summary.json"
    event_paths = list((trial / "node_logs").rglob("events.jsonl"))
    if len(event_paths) != 1:
        raise ValueError("expected one Sentinel event log")
    event_path = event_paths[0]
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    alerts = [row for row in events if row.get("event_type") == "hazard_alert_published"]
    decisions = [row for row in events if row.get("event_type") == "final_decision"]
    verdicts = [row for row in events if row.get("event_type") == "verdict_received"]
    if probe.get("status") != "PASS" or len(alerts) != 5 or len(decisions) != 5 or len(verdicts) != 10:
        raise ValueError("unexpected protocol counts")
    if any(row.get("decision") != "TIMEOUT" for row in decisions):
        raise ValueError("an event did not first finalize as TIMEOUT")
    if any(row.get("accepted") is not False or row.get("reason") != "duplicate finalized verdict" for row in verdicts):
        raise ValueError("late/duplicate verdict was not rejected")
    if len({row["event_id"] for row in decisions}) != 5 or {row["event_id"] for row in alerts} != {row["event_id"] for row in decisions}:
        raise ValueError("event correlation mismatch")
    if "no_matching_scout_verifier" not in (args.scout_snapshot_directory / "scout_process_matches.txt").read_text(encoding="utf-8"):
        raise ValueError("Scout absence snapshot does not match the protocol")
    injections = {row["event_id"]: list(row["late_verdict_monotonic_ns"]) for row in probe["samples"]}
    callbacks_by_id = {}
    for row in verdicts:
        callbacks_by_id.setdefault(row["event_id"], []).append(int(row["monotonic_ns"]))
    callback_latencies = []
    for event_id, times in injections.items():
        callbacks = sorted(callbacks_by_id.get(event_id, []))
        if len(times) != 2 or len(callbacks) != 2:
            raise ValueError("each event must have two injected and two rejected verdicts")
        callback_latencies.extend((callback - injected) / 1e6 for injected, callback in zip(times, callbacks))
    summary = {
        "schema_version": 1,
        "status": "PASS",
        "fault": "late_and_duplicate_scout_verdict_after_timeout",
        "repetitions": 5,
        "timeout_decisions": 5,
        "injected_late_or_duplicate_verdicts": 10,
        "rejected_late_or_duplicate_verdicts": 10,
        "extra_final_decisions": 0,
        "rejection_callback_latency_ms": {
            "n": len(callback_latencies),
            "mean": statistics.mean(callback_latencies),
            "median": statistics.median(callback_latencies),
            "minimum": min(callback_latencies),
            "maximum": max(callback_latencies),
            "p95": percentile(callback_latencies, 0.95),
            "population_standard_deviation": statistics.pstdev(callback_latencies),
        },
        "raw_evidence": {
            "probe_summary": {"path": str(probe_path.resolve()), "sha256": sha256(probe_path)},
            "sentinel_events": {"path": str(event_path.resolve()), "sha256": sha256(event_path)},
            "scout_process_snapshot": {"path": str((args.scout_snapshot_directory / "processes.txt").resolve()), "sha256": sha256(args.scout_snapshot_directory / "processes.txt")},
        },
        "claim_boundary": (
            "For five synthetic Sentinel alerts, two CONFIRMED verdicts were injected only after "
            "the event had finalized as TIMEOUT. All ten were rejected as duplicate finalized "
            "verdicts and created no additional decision. This is deterministic fault injection, "
            "not a natural network-delay distribution or flight/industrial evidence."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
