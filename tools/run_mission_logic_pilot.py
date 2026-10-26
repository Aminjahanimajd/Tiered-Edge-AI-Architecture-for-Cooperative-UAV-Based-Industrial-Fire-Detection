#!/usr/bin/env python3
"""Run the pre-PX4 deterministic mission-logic evidence pilot."""

from __future__ import print_function

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys

from drone_enhanced_core.aerial_mission import (
    DualVehicleMissionController,
    LocalENU,
    MapRejectionMemory,
    ScenarioTarget,
)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def repository_revision(root):
    try:
        return subprocess.check_output(
            ["git", "-C", root, "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def make_target(event_id, target_id="pipe-reflection", created_ns=100):
    return ScenarioTarget(
        event_id,
        target_id,
        LocalENU(12.0, 5.0, 0.0),
        created_ns,
        1000000000,
    )


def complete_dispatch(controller, item, now_ns):
    decision = controller.report_suspect(item, 0.70, 3, now_ns, now_ns)
    if not decision.allowed:
        raise RuntimeError("initial dispatch was unexpectedly suppressed")
    controller.dispatch_scout(item.event_id, now_ns + 1, now_ns + 1)
    controller.scout_at_standoff(item.event_id, now_ns + 2, now_ns + 2)


def run_case(case_name):
    controller = DualVehicleMissionController(
        MapRejectionMemory(
            expiry_ns=30000000000,
            radius_m=1.5,
            override_consecutive_frames=6,
            override_confidence_increase=0.20,
        )
    )
    controller.start_sentinel_patrol(1, 1)
    success = False
    observations = []

    if case_name == "confirmed":
        item = make_target("confirmed-1", "tank-fire")
        complete_dispatch(controller, item, 100)
        controller.apply_verdict(item.event_id, "CONFIRMED", 0.90, 200, 200)
        success = (
            controller.states["sentinel"].value == "CONFIRMED_HOLD"
            and controller.states["scout"].value == "CONFIRMED_HOLD"
        )
    elif case_name == "rejected_resume":
        item = make_target("rejected-1")
        complete_dispatch(controller, item, 100)
        controller.apply_verdict(item.event_id, "REJECTED", 0.05, 200, 200)
        success = (
            controller.states["sentinel"].value == "PATROL"
            and controller.states["scout"].value == "PREFLIGHT"
        )
    elif case_name == "timeout_safe_return":
        item = make_target("timeout-1")
        complete_dispatch(controller, item, 100)
        controller.apply_verdict(item.event_id, "TIMEOUT", 0.0, 200, 200)
        controller.begin_rtl(300, 300, "degraded safety return")
        controller.mark_landed("sentinel", 400, 400)
        controller.mark_landed("scout", 400, 400)
        success = all(value.value == "LANDED" for value in controller.states.values())
    elif case_name in {"repeat_suppressed", "new_target_same_location"}:
        item = make_target("rejected-base")
        complete_dispatch(controller, item, 100)
        controller.apply_verdict(item.event_id, "REJECTED", 0.05, 200, 200)
        target_id = (
            "pipe-reflection"
            if case_name == "repeat_suppressed"
            else "new-physical-fire"
        )
        repeated = make_target("followup-1", target_id, created_ns=250)
        decision = controller.report_suspect(repeated, 0.71, 3, 300, 300)
        observations.append(
            {
                "action": "followup_dispatch_evaluation",
                "allowed": decision.allowed,
                "reason": decision.reason,
                "matched_event_id": decision.matched_event_id,
            }
        )
        success = (
            not decision.allowed
            if case_name == "repeat_suppressed"
            else decision.allowed
        )
    else:
        raise ValueError("unsupported pilot case: {}".format(case_name))

    return {
        "case": case_name,
        "success": bool(success),
        "final_states": {
            name: state.value for name, state in controller.states.items()
        },
        "transitions": controller.transition_records(),
        "suppressed_detections": list(controller.suppressed_detections),
        "observations": observations,
        "claim_boundary": (
            "ROS-independent mission logic only; no PX4, Gazebo, vehicle, "
            "estimator, or physical flight was used."
        ),
    }


def run_pilot():
    cases = [
        "confirmed",
        "rejected_resume",
        "timeout_safe_return",
        "repeat_suppressed",
        "new_target_same_location",
    ]
    results = [run_case(case) for case in cases]
    return {
        "run_type": "ros_independent_mission_logic_pilot",
        "case_count": len(results),
        "passed": sum(1 for result in results if result["success"]),
        "failed": sum(1 for result in results if not result["success"]),
        "cases": results,
    }


def write_evidence(root, output_dir, result):
    os.makedirs(output_dir, exist_ok=False)
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    inputs = [
        os.path.join(root, "config", "project_strengthening_v1.json"),
        os.path.join(root, "config", "simulation_scenarios_v1.json"),
        os.path.join(root, "src", "drone_enhanced_core", "aerial_mission.py"),
        os.path.abspath(__file__),
    ]
    manifest = {
        "schema_version": 1,
        "created_utc": timestamp,
        "repository_revision": repository_revision(root),
        "safety_state": "ROS-independent; no actuator or PX4 adapter imported",
        "inputs": [
            {
                "path": os.path.relpath(path, root).replace(os.sep, "/"),
                "sha256": sha256_file(path),
            }
            for path in inputs
        ],
        "acceptance": "all five deterministic pilot cases pass",
        "status": "PASS" if result["failed"] == 0 else "FAIL",
        "limitations": [
            "No PX4, Gazebo, ROS 2, estimator, network, or physical vehicle.",
            "Scenario coordinates are simulator-only local ENU truth.",
            "This pilot cannot support flight-reliability claims."
        ],
    }
    with open(os.path.join(output_dir, "manifest.json"), "x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    with open(os.path.join(output_dir, "raw_cases.jsonl"), "x", encoding="utf-8") as handle:
        for item in result["cases"]:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    summary = dict(result)
    summary.pop("cases")
    with open(os.path.join(output_dir, "summary.json"), "x", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


def main(argv=None):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir")
    args = parser.parse_args(argv)
    result = run_pilot()
    if args.output_dir:
        write_evidence(root, os.path.abspath(args.output_dir), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
