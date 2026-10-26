#!/usr/bin/env python3
"""Validate one injected-alert/live-Scout hierarchy evidence bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sentinel-probe", type=Path, required=True)
    parser.add_argument("--scout-events", type=Path, required=True)
    parser.add_argument("--scout-manifest", type=Path, required=True)
    parser.add_argument("--diagnostic-frame", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; analysis is non-overwriting")

    sentinel = last_json(args.sentinel_probe)
    events = [
        json.loads(line)
        for line in args.scout_events.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    manifest = json.loads(args.scout_manifest.read_text(encoding="utf-8"))
    by_type = {record["event_type"]: record for record in events}
    required = {
        "first_camera_frame",
        "hazard_alert_received",
        "verification_inference",
        "hazard_verdict_published",
    }
    missing = sorted(required - set(by_type))
    if missing:
        raise ValueError(f"missing Scout event types: {missing}")
    alert = by_type["hazard_alert_received"]
    inference = by_type["verification_inference"]
    verdict = by_type["hazard_verdict_published"]
    event_ids = {record.get("event_id") for record in (alert, inference, verdict)}
    if len(event_ids) != 1 or None in event_ids:
        raise ValueError(f"Scout event identity mismatch: {event_ids}")
    observed = sentinel["observed_verdict"]
    identity_fields = ("experiment_id", "trial_id", "event_id")
    identity_matches = {
        field: observed[field] == verdict[field] == inference[field] == alert[field]
        for field in identity_fields
    }
    identity_matches["verdict"] = observed["verdict"] == verdict["verdict"]
    identity_matches["model_sha256"] = observed["model_sha256"] == manifest["model_sha256"]
    if not all(identity_matches.values()):
        raise ValueError(f"cross-record mismatch: {identity_matches}")
    frame_hash = sha256(args.diagnostic_frame)
    if frame_hash != inference["diagnostic_frame_sha256"]:
        raise ValueError("diagnostic frame hash mismatch")

    summary = {
        "schema_version": 1,
        "status": "PASS",
        "experiment_id": observed["experiment_id"],
        "trial_id": observed["trial_id"],
        "event_id": observed["event_id"],
        "injected_sentinel_confidence": alert["sentinel_confidence"],
        "scout_verdict": observed["verdict"],
        "scout_confidence": observed["confidence"],
        "scout_raw_fire_max": inference["raw_fire_max"],
        "scout_detection_count": inference["detection_count"],
        "scout_queue_delay_ms": inference["queue_delay_ms"],
        "scout_frame_age_at_inference_start_ms": inference["frame_age_at_start_ms"],
        "scout_tflite_inference_ms": inference["inference_latency_ms"],
        "sentinel_measured_injected_alert_to_verdict_callback_ms": sentinel[
            "injected_alert_to_verdict_callback_ms"
        ],
        "logger_dropped_records": inference["logger_dropped_records"],
        "target_coordinates_used_for_scout_inference": inference[
            "target_coordinates_used_for_inference"
        ],
        "camera": {
            "encoding": by_type["first_camera_frame"]["encoding"],
            "decoded_as": by_type["first_camera_frame"]["decoded_as"],
            "width": by_type["first_camera_frame"]["width"],
            "height": by_type["first_camera_frame"]["height"],
        },
        "identity_matches": identity_matches,
        "diagnostic_frame": {
            "path": str(args.diagnostic_frame.resolve()),
            "sha256": frame_hash,
        },
        "raw_evidence": {
            "sentinel_probe_sha256": sha256(args.sentinel_probe),
            "scout_events_sha256": sha256(args.scout_events),
            "scout_manifest_sha256": sha256(args.scout_manifest),
        },
        "claim_boundary": (
            "One stationary negative-scene injected-alert trial. It demonstrates correlated "
            "DDS transport, current-frame Scout TFLite inference, and a returned rejection. "
            "It is not a detection-rate estimate and excludes Sentinel detection latency."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
