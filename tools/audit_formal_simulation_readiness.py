#!/usr/bin/env python3
"""Audit whether the preregistered M8 PX4/Gazebo campaign may start.

This command is intentionally read-only except for its optional JSON report.
It prevents provisional development assets or incomplete fault injection from
being presented as formal repeated-run evidence.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
from pathlib import Path


REQUIRED_AIRFRAME_FIELDS = (
    "mass_with_test_battery_kg",
    "rotor_diagonal_m",
    "body_length_m",
    "body_width_m",
    "body_height_m",
    "camera_translation_body_frd_m",
    "camera_rotation_body_frd_deg",
    "flight_controller_airframe_id",
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def argument_choices(source_path: Path, flag: str):
    """Return literal argparse choices registered for one option flag."""
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    choices = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.Constant) or first.value != flag:
            continue
        for keyword in node.keywords:
            if keyword.arg != "choices" or not isinstance(
                keyword.value, (ast.Tuple, ast.List, ast.Set)
            ):
                continue
            for element in keyword.value.elts:
                if isinstance(element, ast.Constant) and isinstance(
                    element.value, str
                ):
                    choices.add(element.value)
    return choices


def fault_choices(source_path: Path):
    return argument_choices(source_path, "--fault")


def missing_airframe_values(airframes):
    missing = []
    for vehicle_id in ("sentinel", "scout"):
        vehicle = airframes.get(vehicle_id, {})
        for field in REQUIRED_AIRFRAME_FIELDS:
            value = vehicle.get(field)
            if value is None:
                missing.append(f"{vehicle_id}.{field}")
            elif isinstance(value, list) and (not value or any(v is None for v in value)):
                missing.append(f"{vehicle_id}.{field}")
        if not vehicle.get("evidence_photo_ids"):
            missing.append(f"{vehicle_id}.evidence_photo_ids")
    return missing


def planned_counts(project):
    simulation = project["simulation"]
    counts = {
        "nominal_confirmed": int(simulation["confirmed_nominal_runs"]),
        "nominal_rejected": int(simulation["rejected_nominal_runs"]),
        "repeated_confounder": int(simulation["repeated_confounder_runs"]),
        "fault": len(simulation["faults"]) * int(simulation["runs_per_fault"]),
    }
    counts["total"] = sum(counts.values())
    return counts


def audit(root: Path):
    paths = {
        "project": root / "config/project_strengthening_v1.json",
        "scenario": root / "config/simulation_scenarios_v2.json",
        "airframes": root / "simulation/airframes/airframe_measurements_v1.json",
        "runtime": root / "simulation/runtime_lock.json",
        "ros2_runtime": root / "simulation/ros2_runtime_lock.json",
        "launch_contract": root / "simulation/development_launch_contract_v1.json",
        "runner": root / "tools/run_hierarchical_px4_mission.py",
        "mission_node": root / "tools/px4_sim_hierarchical_mission.py",
        "repeated_confounder_pilot": (
            root / "simulation/pilots/repeated_confounder_v1.json"
        ),
        "mission_node_restart_pilot": (
            root / "simulation/pilots/mission_node_restart_v1.json"
        ),
    }
    missing_files = [str(path) for path in paths.values() if not path.is_file()]
    if missing_files:
        return {
            "schema_version": 1,
            "status": "BLOCKED",
            "blockers": [f"required file missing: {path}" for path in missing_files],
        }

    project = load_json(paths["project"])
    scenario = load_json(paths["scenario"])
    airframes = load_json(paths["airframes"])
    runtime = load_json(paths["runtime"])
    ros2_runtime = load_json(paths["ros2_runtime"])
    launch_contract = load_json(paths["launch_contract"])
    repeated_pilot = load_json(paths["repeated_confounder_pilot"])
    restart_pilot = load_json(paths["mission_node_restart_pilot"])
    expected_faults = set(project["simulation"]["faults"])
    runner_faults = fault_choices(paths["runner"])
    node_faults = fault_choices(paths["mission_node"])
    runner_modes = argument_choices(paths["runner"], "--runner-mode")
    node_modes = argument_choices(paths["mission_node"], "--runner-mode")
    blockers = []
    warnings = []

    missing_values = missing_airframe_values(airframes)
    if missing_values:
        blockers.append(
            "physical airframe characterization is incomplete: "
            + ", ".join(missing_values)
        )
    if airframes.get("formal_model_generation_allowed") is not True:
        blockers.append("formal_model_generation_allowed is not true")
    if airframes.get("formal_asset_status") != "GENERATED_AND_HASHED":
        blockers.append("formal parameterized airframe assets are not generated and hashed")
    if scenario.get("status") != "FORMAL_FROZEN":
        blockers.append("simulation_scenarios_v2.json is not marked FORMAL_FROZEN")
    for vehicle_id, row in scenario.get("vehicles", {}).items():
        if row.get("parameter_status") != "MEASURED_AND_FROZEN":
            blockers.append(f"{vehicle_id} simulator parameters are not measured and frozen")

    missing_runner_faults = sorted(expected_faults - runner_faults)
    missing_node_faults = sorted(expected_faults - node_faults)
    if missing_runner_faults:
        blockers.append(
            "orchestration runner lacks fault choices: "
            + ", ".join(missing_runner_faults)
        )
    if missing_node_faults:
        blockers.append(
            "mission node lacks fault implementations: "
            + ", ".join(missing_node_faults)
        )

    if "repeated_confounder" not in runner_modes:
        blockers.append(
            "repeated-confounder mode is not exposed by the orchestration runner"
        )
    if "repeated_confounder" not in node_modes:
        blockers.append(
            "repeated-confounder PX4 mission mode is not implemented in the mission node"
        )
    if repeated_pilot.get("status") != "PASS":
        blockers.append("repeated-confounder Gazebo development pilot is not PASS")
    if restart_pilot.get("status") != "PASS":
        blockers.append("mission-node-restart Gazebo development pilot is not PASS")

    if runtime.get("px4_ref") != project["simulation"].get("px4_version"):
        blockers.append("PX4 runtime reference differs from the frozen project contract")
    if runtime.get("formal_runs_require_clean_runtime") is not True:
        blockers.append("runtime does not require a clean formal PX4 checkout")
    if ros2_runtime.get("build_status") != "PASS":
        blockers.append("the pinned ROS 2 workspace build is not recorded as PASS")
    if launch_contract.get("measurement_gate_passed") is not True:
        blockers.append("the simulator launch contract is still development-only")

    models = [
        scenario.get("vehicles", {}).get(role, {}).get("simulation_model")
        for role in ("sentinel", "scout")
    ]
    if None in models or len(set(models)) != 2:
        blockers.append("the formal scenario does not identify two distinct vehicle models")

    if project.get("deadline") != "2026-09-20":
        warnings.append("project configuration deadline differs from its original frozen value")

    hashes = {name: sha256(path) for name, path in paths.items()}
    return {
        "schema_version": 1,
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "READY" if not blockers else "BLOCKED",
        "purpose": "M8 formal dual-PX4/Gazebo campaign readiness gate",
        "safety_state": "simulation-only audit; no physical vehicle interface or actuation",
        "planned_runs": planned_counts(project),
        "expected_faults": sorted(expected_faults),
        "runner_faults": sorted(runner_faults),
        "mission_node_faults": sorted(node_faults),
        "runner_modes": sorted(runner_modes),
        "mission_node_modes": sorted(node_modes),
        "blockers": blockers,
        "warnings": warnings,
        "input_sha256": hashes,
        "acceptance": (
            "READY only when physical proxy parameters and formal assets are frozen, "
            "all preregistered faults are implemented end-to-end, the repeated-confounder "
            "mode exists, and the pinned PX4/ROS 2 runtime contract remains valid"
        ),
        "claim_boundary": (
            "READY authorizes the repeated simulator campaign only. It does not establish "
            "physical flight safety, industrial deployment, or vision-derived localization."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = audit(args.root.resolve())
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise FileExistsError(output)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
