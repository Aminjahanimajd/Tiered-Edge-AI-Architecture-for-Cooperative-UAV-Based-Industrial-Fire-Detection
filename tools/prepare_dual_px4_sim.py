#!/usr/bin/env python3
"""Validate and install versioned dual-PX4 Gazebo development assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path


MODEL_NAMES = ("x500_v2_sentinel_proxy", "modalai_devkit_scout_proxy")
WORLD_NAME = "industrial_inspection_proxy_v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def required_measurements_present(measurements: dict) -> bool:
    fields = (
        "mass_with_test_battery_kg",
        "rotor_diagonal_m",
        "body_length_m",
        "body_width_m",
        "body_height_m",
        "camera_translation_body_frd_m",
        "camera_rotation_body_frd_deg",
        "flight_controller_airframe_id",
    )
    for vehicle in ("sentinel", "scout"):
        row = measurements[vehicle]
        for field in fields:
            value = row.get(field)
            if value is None:
                return False
            if isinstance(value, list) and any(item is None for item in value):
                return False
    return (
        bool(measurements.get("formal_model_generation_allowed"))
        and measurements.get("formal_asset_status") == "MEASURED_PARAMETERS_APPLIED_AND_VERIFIED"
    )


def validate_assets(root: Path, scenarios: dict) -> list[Path]:
    paths = []
    observed_names = set()
    for model_name in MODEL_NAMES:
        model_dir = root / "simulation" / "models" / model_name
        model_sdf = model_dir / "model.sdf"
        model_config = model_dir / "model.config"
        parsed = ET.parse(model_sdf)
        observed = parsed.getroot().find("model").attrib["name"]
        if observed != model_name:
            raise ValueError("model directory/name mismatch: {}".format(model_name))
        if parsed.getroot().find(".//include/uri").text.strip() != "x500":
            raise ValueError("{} must pin the PX4 x500 development dynamics".format(model_name))
        ET.parse(model_config)
        observed_names.add(observed)
        paths.extend((model_sdf, model_config))
    if len(observed_names) != 2:
        raise ValueError("Sentinel and Scout proxy model names must be distinct")
    configured = {row["simulation_model"] for row in scenarios["vehicles"].values()}
    if configured != observed_names:
        raise ValueError("scenario vehicle models do not match installed assets")
    world = root / "simulation" / "worlds" / (WORLD_NAME + ".sdf")
    world_root = ET.parse(world).getroot().find("world")
    if world_root.attrib["name"] != WORLD_NAME:
        raise ValueError("world name mismatch")
    required_world_models = {
        "ground_plane", "tank_a", "tank_c", "pipe_rack_b",
        "aisle_wall_west", "aisle_wall_east",
        "sentinel_home_marker", "scout_home_marker",
    }
    observed_world_models = {node.attrib["name"] for node in world_root.findall("model")}
    missing = required_world_models - observed_world_models
    if missing:
        raise ValueError("world is missing models: {}".format(sorted(missing)))
    paths.append(world)
    return paths


def launch_contract(runtime: Path, scenarios: dict) -> dict:
    binary = runtime / "build" / "px4_sitl_default" / "bin" / "px4"
    commands = {}
    for vehicle_id in ("sentinel", "scout"):
        row = scenarios["vehicles"][vehicle_id]
        instance = int(row["px4_instance"])
        commands[vehicle_id] = {
            "environment": {
                "PX4_SYS_AUTOSTART": "4001",
                "PX4_SIM_MODEL": "gz_" + row["simulation_model"],
                "PX4_GZ_WORLD": WORLD_NAME,
                "PX4_GZ_STANDALONE": "0" if vehicle_id == "sentinel" else "1",
                "PX4_GZ_MODEL_POSE": ",".join(str(value) for value in row["home_enu_m"]),
                "PX4_UXRCE_DDS_NS": row["ros_namespace"].lstrip("/"),
                "PX4_UXRCE_DDS_PORT": "8888",
            },
            "executable": str(binary),
            "arguments": ["-i", str(instance)],
            "expected_mavlink_system_id": int(row["mavlink_system_id"]),
            "expected_dds_key": instance + 1,
            "log_directory": "artifacts/experiments/dual_px4/<run_id>/" + vehicle_id,
        }
    return commands


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime",
        type=Path,
        default=Path("/home/sefroyek/drone_enhanced_sim/PX4-Autopilot-v1.17.0"),
    )
    parser.add_argument("--formal", action="store_true")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    scenarios_path = root / "config" / "simulation_scenarios_v1.json"
    measurements_path = root / "simulation" / "airframes" / "airframe_measurements_v1.json"
    scenarios = json.loads(scenarios_path.read_text(encoding="utf-8"))
    measurements = json.loads(measurements_path.read_text(encoding="utf-8"))
    if args.formal and not required_measurements_present(measurements):
        raise SystemExit("BLOCKED: formal assets require the August 24 physical measurement freeze")
    assets = validate_assets(root, scenarios)
    if not (args.runtime / "build" / "px4_sitl_default" / "bin" / "px4").is_file():
        raise SystemExit("BLOCKED: pinned PX4 SITL binary is absent")
    if args.install:
        for model_name in MODEL_NAMES:
            destination = args.runtime / "Tools" / "simulation" / "gz" / "models" / model_name
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(root / "simulation" / "models" / model_name, destination)
        shutil.copy2(
            root / "simulation" / "worlds" / (WORLD_NAME + ".sdf"),
            args.runtime / "Tools" / "simulation" / "gz" / "worlds" / (WORLD_NAME + ".sdf"),
        )
    result = {
        "schema_version": 1,
        "mode": "FORMAL" if args.formal else "DEVELOPMENT_PROXY",
        "installed": bool(args.install),
        "measurement_gate_passed": required_measurements_present(measurements),
        "runtime": str(args.runtime),
        "assets": [{"path": str(path.relative_to(root)).replace("\\", "/"), "sha256": sha256(path)} for path in assets],
        "vehicles": launch_contract(args.runtime, scenarios),
        "claim_boundary": "Development assets are distinct calibrated-proxy scaffolds; no flight or mission result is produced by this command.",
    }
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
