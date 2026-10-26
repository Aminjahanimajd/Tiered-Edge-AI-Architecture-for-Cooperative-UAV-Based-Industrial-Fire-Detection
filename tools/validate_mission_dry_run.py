#!/usr/bin/env python3
"""Produce hashed evidence for the safety-locked mission dry run."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

from drone_enhanced_core.mission_dry_run import (
    ActuationBlocked,
    DryRunMissionController,
    SafetyLockedFlightAdapter,
    lawnmower_search_plan,
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"refusing to overwrite {arguments.output}")
    started = time.monotonic_ns()
    plan = lawnmower_search_plan(4.0, 6.0, 2.0, 3.0)
    adapter = SafetyLockedFlightAdapter()
    controller = DryRunMissionController(plan, adapter)
    controller.start_search_preview()
    previews = [controller.preview_next_waypoint() for _ in plan]
    controller.begin_verification_hold("dryrun-rejected")
    controller.apply_verdict("dryrun-rejected", "REJECTED")
    controller.begin_verification_hold("dryrun-confirmed")
    controller.apply_verdict("dryrun-confirmed", "CONFIRMED")
    blocked = []
    for name, command in (
        ("arm", adapter.arm),
        ("takeoff", lambda: adapter.takeoff(3.0)),
        ("goto", lambda: adapter.goto(plan[0])),
        ("set_velocity", lambda: adapter.set_velocity(1.0, 0.0, 0.0)),
    ):
        try:
            command()
        except ActuationBlocked as error:
            blocked.append({"command": name, "blocked": True, "reason": str(error)})
    source = Path(__file__).resolve().parents[1] / "src" / "drone_enhanced_core" / "mission_dry_run.py"
    result = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "status": "pass" if len(blocked) == 4 and all(not item["transmitted_to_vehicle"] for item in previews) else "fail",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "elapsed_monotonic_ns": time.monotonic_ns() - started,
        "safety_state": "propellers and vehicles not required; no network or vehicle object created",
        "frame": "arbitrary local ENU preview; not GPS or estimated localization",
        "plan": [asdict(item) for item in plan],
        "previews": previews,
        "transitions": controller.transitions,
        "final_mode": controller.mode.value,
        "blocked_actuation_attempts": blocked,
        "source_sha256": file_sha256(source),
        "validator_sha256": file_sha256(Path(__file__).resolve()),
        "acceptance_criterion": "all previews remain untransmitted and arm, takeoff, goto, and velocity calls are blocked",
        "interpretation": "mission logic is implemented and offline-tested only",
        "limitations": [
            "No vehicle, flight controller, estimator, GPS, or network was used.",
            "The local frame is arbitrary and does not establish geographic localization.",
            "The search dimensions are illustrative configuration, not a validated industrial mission.",
        ],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
