#!/usr/bin/env python3
"""Validate and summarize a bounded receive-only Pixhawk telemetry capture."""

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trial-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; analysis is non-overwriting")

    trial = args.trial_directory
    telemetry_path = trial / "telemetry.json"
    telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
    exit_code = int((trial / "probe_exit_code.txt").read_text(encoding="utf-8").strip())
    safety = (trial / "safety_state.txt").read_text(encoding="utf-8").strip()
    mavproxy_after = (trial / "mavproxy_after.txt").read_text(encoding="utf-8", errors="replace")

    if telemetry.get("status") != "PASS" or exit_code != 0:
        raise ValueError("receive-only probe did not complete successfully")
    if telemetry.get("message_count", 0) <= 0 or telemetry.get("first_heartbeat") is None:
        raise ValueError("capture lacks telemetry or a heartbeat")
    if "no send" not in safety.lower() or "active (running)" not in mavproxy_after.lower():
        raise ValueError("safety declaration or post-probe MAVProxy restoration is missing")

    message_types = {str(key): int(value) for key, value in telemetry["message_types"].items()}
    required_presence = {
        name: message_types.get(name, 0)
        for name in ("HEARTBEAT", "ESTIMATOR_STATUS", "GPS_RAW_INT", "LOCAL_POSITION_NED",
                     "ODOMETRY", "BATTERY_STATUS", "SYS_STATUS", "VIBRATION")
    }
    if required_presence["HEARTBEAT"] <= 0:
        raise ValueError("heartbeat count is zero")

    summary = {
        "schema_version": 1,
        "status": "PASS",
        "trial_id": trial.name,
        "safety_state": safety,
        "device": telemetry["device"],
        "baud": int(telemetry["baud"]),
        "duration_seconds": float(telemetry["duration_seconds"]),
        "message_count": int(telemetry["message_count"]),
        "message_types": dict(sorted(message_types.items())),
        "selected_message_type_counts": required_presence,
        "first_heartbeat": telemetry["first_heartbeat"],
        "mavproxy_restored_active": True,
        "raw_evidence": {
            "telemetry": {"path": str(telemetry_path.resolve()), "sha256": sha256(telemetry_path)},
            "safety_state": {"path": str((trial / "safety_state.txt").resolve()), "sha256": sha256(trial / "safety_state.txt")},
            "mavproxy_after": {"path": str((trial / "mavproxy_after.txt").resolve()), "sha256": sha256(trial / "mavproxy_after.txt")},
            "trial_manifest": {"path": str((trial / "sha256_manifest.txt").resolve()), "sha256": sha256(trial / "sha256_manifest.txt")},
        },
        "claim_boundary": (
            "The capture demonstrates receive-only MAVLink availability and message-type presence "
            "during one bounded stationary interval with propellers removed. Message counts do not "
            "establish estimator validity, localization accuracy, command routing, flight readiness, "
            "or operational reliability."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
