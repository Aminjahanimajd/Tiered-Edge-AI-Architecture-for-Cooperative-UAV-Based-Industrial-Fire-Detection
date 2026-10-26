#!/usr/bin/env python3
"""Validate the frozen strengthening and simulator contracts."""

from __future__ import print_function

import argparse
import json
import os
import sys


EXPECTED_MODELS = {
    "yolov8n_416",
    "yolov8n_640",
    "yolov8s_416",
    "yolov8s_640",
    "ssd_mobilenet_v2_fpnlite_320",
    "efficientdet_lite0",
}
EXPECTED_STATES = {
    "PREFLIGHT",
    "TAKEOFF",
    "PATROL",
    "SUSPECT_HOLD",
    "SCOUT_DISPATCH",
    "VERIFYING",
    "CONFIRMED_HOLD",
    "REJECTED_RESUME",
    "DEGRADED",
    "RTL",
    "LANDED",
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def validate(project, scenarios, airframes, runtime):
    errors = []
    model_ids = {item.get("id") for item in project.get("candidate_models", [])}
    if model_ids != EXPECTED_MODELS:
        errors.append("candidate model registry does not match the six-model scope")
    if project.get("external_data", {}).get("training_use_prohibited") is not True:
        errors.append("external benchmark data must be prohibited from training")
    if project.get("simulation", {}).get("px4_version") != "v1.17.0":
        errors.append("formal simulation must pin PX4 v1.17.0")
    vehicles = scenarios.get("vehicles", {})
    if set(vehicles) != {"sentinel", "scout"}:
        errors.append("scenario must define exactly Sentinel and Scout")
    elif vehicles["sentinel"].get("simulation_model") == vehicles["scout"].get("simulation_model"):
        errors.append("Sentinel and Scout simulation models must be distinct")
    namespaces = [item.get("ros_namespace") for item in vehicles.values()]
    instances = [item.get("px4_instance") for item in vehicles.values()]
    system_ids = [item.get("mavlink_system_id") for item in vehicles.values()]
    if len(set(namespaces)) != 2 or len(set(instances)) != 2 or len(set(system_ids)) != 2:
        errors.append("vehicle namespaces, instances, and MAVLink IDs must be unique")
    if scenarios.get("coordinate_frame") != "local_enu_simulator_ground_truth":
        errors.append("scenario coordinate frame must retain the simulator-truth boundary")
    if runtime.get("formal_runs_require_clean_runtime") is not True:
        errors.append("formal simulation must require a clean isolated runtime")
    if runtime.get("px4_ref") != project.get("simulation", {}).get("px4_version"):
        errors.append("PX4 runtime and project contract versions disagree")
    if airframes.get("formal_model_generation_allowed") is True:
        for role in ("sentinel", "scout"):
            values = airframes.get(role, {})
            required = [
                "mass_with_test_battery_kg",
                "rotor_diagonal_m",
                "body_length_m",
                "body_width_m",
                "body_height_m",
                "flight_controller_airframe_id",
            ]
            if any(values.get(name) is None for name in required):
                errors.append(
                    "{} formal model enabled with missing physical values".format(role)
                )
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=os.path.dirname(os.path.dirname(__file__)))
    args = parser.parse_args(argv)
    paths = {
        "project": os.path.join(args.root, "config", "project_strengthening_v1.json"),
        "scenarios": os.path.join(args.root, "config", "simulation_scenarios_v1.json"),
        "airframes": os.path.join(
            args.root, "simulation", "airframes", "airframe_measurements_v1.json"
        ),
        "runtime": os.path.join(args.root, "simulation", "runtime_lock.json"),
    }
    loaded = {name: load_json(path) for name, path in paths.items()}
    errors = validate(
        loaded["project"], loaded["scenarios"], loaded["airframes"], loaded["runtime"]
    )
    result = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "candidate_model_count": len(loaded["project"]["candidate_models"]),
        "vehicle_models": {
            role: data["simulation_model"]
            for role, data in loaded["scenarios"]["vehicles"].items()
        },
        "formal_model_generation_allowed": loaded["airframes"][
            "formal_model_generation_allowed"
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
