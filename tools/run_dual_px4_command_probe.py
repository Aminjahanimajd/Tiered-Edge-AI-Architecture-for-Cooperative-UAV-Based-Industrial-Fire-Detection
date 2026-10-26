#!/usr/bin/env python3
"""Orchestrate two sequential SITL-only PX4 ROS offboard command probes."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import subprocess
import threading
import time
from pathlib import Path

import run_dual_px4_spawn_probe as spawn_probe


VEHICLE_PROBES = {
    "sentinel": {"home_enu": (0.0, 0.0, 0.0), "target_enu": (3.0, 3.0, 3.0)},
    "scout": {"home_enu": (-4.0, 0.0, 0.0), "target_enu": (0.0, 3.0, 3.0)},
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_result(text):
    decoder = json.JSONDecoder()
    results = []
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("status") in {"PASS", "FAIL"}:
            results.append(value)
    if not results:
        raise ValueError("probe stdout contains no status result")
    return results[-1]


def docker_probe_command(container, root, vehicle, output):
    row = VEHICLE_PROBES[vehicle]
    relative_output = output.relative_to(root).as_posix()
    values = [
        "python3", "/project/tools/px4_sim_offboard_vehicle.py",
        "--vehicle-id", vehicle,
        "--home-enu", *[str(value) for value in row["home_enu"]],
        "--target-enu", *[str(value) for value in row["target_enu"]],
        "--takeoff-altitude-m", "3.0",
        "--hold-s", "3.0",
        "--total-timeout-s", "90.0",
        "--output", "/project/" + relative_output,
    ]
    quoted = " ".join(subprocess.list2cmdline([value]) for value in values)
    shell = (
        "source /opt/ros/jazzy/setup.bash && "
        "source /ws/install/setup.bash && "
        "export PYTHONPATH=/project/src:${PYTHONPATH:-} && "
        "export DRONE_ENHANCED_SIMULATION_ONLY=I_ACKNOWLEDGE_PX4_SITL_ONLY && "
        + quoted
    )
    return ["docker.exe", "exec", container, "bash", "-lc", shell]


def run(root, runtime, output, container, agent_ip, duration_s=210.0, settle_s=16.0):
    root = Path(root).resolve()
    runtime = Path(runtime).resolve()
    output = Path(output)
    output = (root / output).resolve() if not output.is_absolute() else output.resolve()
    if output.exists():
        raise FileExistsError(output)
    if duration_s < 120:
        raise ValueError("duration_s must be at least 120 seconds")
    output.mkdir(parents=True)
    prepared_commands = {
        vehicle: docker_probe_command(
            container, root, vehicle, output / f"{vehicle}_events.jsonl"
        )
        for vehicle in VEHICLE_PROBES
    }
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    holder = {}
    stop_event = threading.Event()

    def launch():
        try:
            holder["spawn"] = spawn_probe.run(
                root, runtime, output / "spawn", duration_s, agent_ip, stop_event
            )
        except BaseException as exc:
            holder["error"] = repr(exc)

    thread = threading.Thread(target=launch, daemon=False)
    thread.start()
    time.sleep(settle_s)

    topic_command = [
        "docker.exe", "exec", container, "bash", "-lc",
        "source /opt/ros/jazzy/setup.bash && "
        "source /ws/install/setup.bash && ros2 topic list -t",
    ]
    topics = subprocess.run(
        topic_command, text=True, capture_output=True, timeout=25
    )
    (output / "ros2_topic_list.txt").write_text(topics.stdout, encoding="utf-8")
    (output / "ros2_topic_list.stderr.txt").write_text(
        topics.stderr, encoding="utf-8"
    )
    required_topics = [
        f"/{vehicle}/fmu/in/vehicle_command" for vehicle in VEHICLE_PROBES
    ] + [
        f"/{vehicle}/fmu/out/vehicle_status_v1" for vehicle in VEHICLE_PROBES
    ]
    topic_checks = {topic: topic in topics.stdout for topic in required_topics}

    probes = {}
    for vehicle in ("sentinel", "scout"):
        log_path = output / f"{vehicle}_events.jsonl"
        command = prepared_commands[vehicle]
        completed = subprocess.run(
            command, text=True, capture_output=True, timeout=110
        )
        stdout_path = output / f"{vehicle}_probe.stdout.txt"
        stderr_path = output / f"{vehicle}_probe.stderr.txt"
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
        try:
            parsed = parse_result(completed.stdout)
        except ValueError as exc:
            parsed = {"status": "FAIL", "failure_reason": str(exc)}
        probes[vehicle] = {
            "command": command,
            "returncode": completed.returncode,
            "result": parsed,
            "stdout_sha256": sha256(stdout_path),
            "stderr_sha256": sha256(stderr_path),
            "event_log_sha256": sha256(log_path) if log_path.is_file() else None,
        }

    stop_event.set()
    thread.join(timeout=30)
    if thread.is_alive():
        raise TimeoutError("dual-PX4 spawn did not terminate")
    spawn_status = holder.get("spawn", {}).get("status", "ERROR")
    status = "PASS" if (
        topics.returncode == 0
        and all(topic_checks.values())
        and spawn_status == "PASS"
        and all(
            row["returncode"] == 0 and row["result"].get("status") == "PASS"
            for row in probes.values()
        )
    ) else "FAIL"
    result = {
        "schema_version": 1,
        "run_type": "dual_px4_ros2_offboard_command_development_probe",
        "started_utc": started,
        "completed_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": status,
        "safety_state": "SITL only; explicit simulator token; no physical transport",
        "container": container,
        "agent_ip": agent_ip,
        "spawn_status": spawn_status,
        "spawn_error": holder.get("error"),
        "topic_checks": topic_checks,
        "probes": probes,
        "acceptance": (
            "both distinct PX4 SITL vehicles verify identity, arm in offboard mode, "
            "take off, reach a bounded translated setpoint, hold, land, and disarm"
        ),
        "claim_boundary": (
            "Development command-path evidence using provisional airframe proxies. "
            "Not a hierarchical mission, formal simulation run, physical flight, "
            "airframe certification, or reliability estimate."
        ),
        "source_hashes": {
            "runner": sha256(Path(__file__)),
            "vehicle_node": sha256(root / "tools/px4_sim_offboard_vehicle.py"),
            "safety_core": sha256(root / "src/drone_enhanced_core/px4_sim_adapter.py"),
            "scenario": sha256(root / "config/simulation_scenarios_v1.json"),
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "status": status,
        "spawn_status": spawn_status,
        "topic_checks": topic_checks,
        "vehicle_results": {
            key: value["result"] for key, value in probes.items()
        },
    }, indent=2, sort_keys=True))
    return result


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime", type=Path,
        default=Path("/home/sefroyek/drone_enhanced_sim/PX4-Autopilot-v1.17.0"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--container", default="drone-xrce-ros-probe")
    parser.add_argument("--agent-ip", required=True)
    parser.add_argument("--duration-s", type=float, default=210.0)
    parser.add_argument("--settle-s", type=float, default=16.0)
    args = parser.parse_args()
    result = run(
        root, args.runtime, args.output, args.container,
        args.agent_ip, args.duration_s, args.settle_s,
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
