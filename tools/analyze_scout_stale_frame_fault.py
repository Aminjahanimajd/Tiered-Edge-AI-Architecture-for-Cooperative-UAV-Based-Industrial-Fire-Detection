#!/usr/bin/env python3
"""Validate a live-frame preflight followed by a Scout stale-stream fault."""

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


def describe(values: list[float]) -> dict:
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
        "p95": percentile(values, 0.95),
        "population_standard_deviation": statistics.pstdev(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trial-directory", type=Path, required=True)
    parser.add_argument("--preflight-count", type=int, default=3)
    parser.add_argument("--fault-count", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; analysis is non-overwriting")

    trial = args.trial_directory
    event_path = trial / "events.jsonl"
    manifest_path = trial / "session_manifest.json"
    before_stop_path = trial / "events_before_bridge_stop.jsonl"
    exit_path = trial / "node_exit_code.txt"
    probes = sorted((trial / "probes").glob("*.json"))
    expected_total = args.preflight_count + args.fault_count
    if len(probes) != expected_total:
        raise ValueError(f"expected {expected_total} probes; found {len(probes)}")

    probe_rows = [last_json(path) for path in probes]
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    before_stop = [json.loads(line) for line in before_stop_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    alerts = [row for row in events if row.get("event_type") == "hazard_alert_received"]
    verdicts = [row for row in events if row.get("event_type") == "hazard_verdict_published"]
    inferences = [row for row in events if row.get("event_type") == "verification_inference"]
    first_frames = [row for row in before_stop if row.get("event_type") == "first_camera_frame"]
    if len(first_frames) != 1:
        raise ValueError("exactly one first-camera-frame record was not preserved before bridge stop")

    preflight_prefix = f"{manifest['trial_id']}-preflight-"
    fault_prefix = f"{manifest['trial_id']}-fault-"
    preflight_probes = [row for row in probe_rows if row["observed_verdict"]["event_id"].startswith(preflight_prefix)]
    fault_probes = [row for row in probe_rows if row["observed_verdict"]["event_id"].startswith(fault_prefix)]
    preflight_inferences = [row for row in inferences if row.get("event_id", "").startswith(preflight_prefix)]
    fault_inferences = [row for row in inferences if row.get("event_id", "").startswith(fault_prefix)]
    if len(preflight_probes) != args.preflight_count or len(fault_probes) != args.fault_count:
        raise ValueError("preflight/fault probe counts do not match the protocol")
    if len(alerts) != expected_total or len(verdicts) != expected_total:
        raise ValueError("Scout alert/verdict counts do not match all injected probes")
    if len(preflight_inferences) != args.preflight_count or fault_inferences:
        raise ValueError("inference occurred in the wrong protocol phase")

    ids_by_source = [
        {row["observed_verdict"]["event_id"] for row in probe_rows},
        {row["event_id"] for row in alerts},
        {row["event_id"] for row in verdicts},
    ]
    if not (ids_by_source[0] == ids_by_source[1] == ids_by_source[2]):
        raise ValueError("event identity mismatch across Sentinel probes and Scout logs")
    for row in preflight_probes:
        observed = row["observed_verdict"]
        if row.get("status") != "PASS" or observed.get("verdict") == "ERROR":
            raise ValueError("live preflight did not produce a normal model verdict")
        if observed.get("model_sha256") != manifest.get("model_sha256"):
            raise ValueError("preflight probe/manifest model hash mismatch")
    for row in fault_probes:
        observed = row["observed_verdict"]
        if row.get("status") != "PASS" or observed.get("verdict") != "ERROR" or observed.get("reason") != "stale_frame":
            raise ValueError("fault probe did not produce a correlated ERROR/stale_frame verdict")
        if observed.get("model_sha256") != manifest.get("model_sha256"):
            raise ValueError("fault probe/manifest model hash mismatch")

    exit_code = int(exit_path.read_text(encoding="utf-8").strip())
    if exit_code not in (0, 124, 130):
        raise ValueError(f"unexpected bounded node exit code: {exit_code}")
    fault_latencies = [float(row["injected_alert_to_verdict_callback_ms"]) for row in fault_probes]
    preflight_latencies = [float(row["injected_alert_to_verdict_callback_ms"]) for row in preflight_probes]
    inference_latencies = [float(row["inference_latency_ms"]) for row in preflight_inferences]
    summary = {
        "schema_version": 1,
        "status": "PASS",
        "fault": "scout_ros_camera_stream_stale_after_live_preflight",
        "live_preflight": {
            "first_camera_frame_records": len(first_frames),
            "correlated_model_verdicts": len(preflight_probes),
            "verification_inferences": len(preflight_inferences),
            "probe_latency_ms": describe(preflight_latencies),
            "inference_latency_ms": describe(inference_latencies),
        },
        "fault_phase": {
            "expected_repetitions": args.fault_count,
            "correlated_error_verdicts": len(fault_probes),
            "reason": "stale_frame",
            "verification_inferences": len(fault_inferences),
            "probe_latency_ms": describe(fault_latencies),
        },
        "unique_event_ids": len(ids_by_source[0]),
        "node_exit_code": exit_code,
        "model_sha256": manifest["model_sha256"],
        "raw_evidence": {
            "probe_files": [{"path": str(path.resolve()), "sha256": sha256(path)} for path in probes],
            "scout_events": {"path": str(event_path.resolve()), "sha256": sha256(event_path)},
            "events_before_bridge_stop": {"path": str(before_stop_path.resolve()), "sha256": sha256(before_stop_path)},
            "scout_manifest": {"path": str(manifest_path.resolve()), "sha256": sha256(manifest_path)},
        },
        "claim_boundary": (
            "A live ROS camera stream and three normal model inferences were demonstrated before "
            "the camera bridge was stopped. Five later stationary injected alerts each produced a "
            "correlated ERROR/stale_frame verdict without inference. This tests the ROS stream-loss "
            "boundary, not physical camera-hardware failure, flight safety, or industrial reliability."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
