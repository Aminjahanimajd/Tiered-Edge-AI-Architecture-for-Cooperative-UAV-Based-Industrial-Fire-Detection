#!/usr/bin/env python3
"""Capture simultaneous Sentinel and Scout PX4 topics from an isolated ROS container."""

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

REQUIRED = (
    "/sentinel/fmu/out/vehicle_status_v1",
    "/sentinel/fmu/out/vehicle_local_position_v1",
    "/sentinel/fmu/in/vehicle_command",
    "/scout/fmu/out/vehicle_status_v1",
    "/scout/fmu/out/vehicle_local_position_v1",
    "/scout/fmu/in/vehicle_command",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_topic_list(text: str) -> dict:
    topics = {}
    for line in text.splitlines():
        if " [" in line and line.endswith("]"):
            name, message_type = line.rsplit(" [", 1)
            topics[name] = message_type[:-1]
    return topics


def run(root: Path, runtime: Path, output: Path, container: str, duration_s: float, settle_s: float) -> dict:
    root, runtime, output = Path(root), Path(runtime), Path(output)
    if output.exists():
        raise FileExistsError("output directory already exists")
    if settle_s >= duration_s - 5:
        raise ValueError("settle_s must leave at least five seconds for capture")
    output.mkdir(parents=True)
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    holder: dict = {}

    def launch() -> None:
        try:
            holder["spawn"] = spawn_probe.run(
                root, runtime, output / "spawn", duration_s
            )
        except BaseException as exc:
            holder["error"] = repr(exc)

    thread = threading.Thread(target=launch, daemon=False)
    thread.start()
    time.sleep(settle_s)
    command = [
        "docker.exe", "exec", container, "bash", "-lc",
        "source /opt/ros/jazzy/setup.bash && "
        "source /ws/install/setup.bash && ros2 topic list -t",
    ]
    capture = subprocess.run(command, text=True, capture_output=True, timeout=25)
    (output / "ros2_topic_list.txt").write_text(capture.stdout, encoding="utf-8")
    (output / "ros2_topic_list.stderr.txt").write_text(capture.stderr, encoding="utf-8")

    samples = {}
    for vehicle in ("sentinel", "scout"):
        topic = f"/{vehicle}/fmu/out/vehicle_status_v1"
        sample_command = [
            "docker.exe", "exec", container, "bash", "-lc",
            "source /opt/ros/jazzy/setup.bash && "
            "source /ws/install/setup.bash && "
            f"timeout 8s ros2 topic echo {topic} "
            "px4_msgs/msg/VehicleStatus --once --qos-reliability best_effort",
        ]
        sample = subprocess.run(
            sample_command, text=True, capture_output=True, timeout=15
        )
        sample_path = output / f"{vehicle}_vehicle_status_sample.txt"
        sample_path.write_text(sample.stdout, encoding="utf-8")
        (output / f"{vehicle}_vehicle_status_sample.stderr.txt").write_text(
            sample.stderr, encoding="utf-8"
        )
        samples[vehicle] = {
            "topic": topic,
            "command": sample_command,
            "returncode": sample.returncode,
            "received": sample.returncode == 0 and bool(sample.stdout.strip()),
            "raw_sha256": sha256(sample_path),
        }

    thread.join(timeout=duration_s + 20)
    if thread.is_alive():
        raise TimeoutError("spawn probe thread did not terminate")

    topics = parse_topic_list(capture.stdout)
    checks = {name: name in topics for name in REQUIRED}
    spawn_status = holder.get("spawn", {}).get("status", "ERROR")
    delivery_passed = all(row["received"] for row in samples.values())
    status = (
        "PASS"
        if (
            capture.returncode == 0
            and spawn_status == "PASS"
            and all(checks.values())
            and delivery_passed
        )
        else "FAIL"
    )
    result = {
        "schema_version": 1,
        "run_type": "dual_px4_ros2_graph_and_delivery_development_probe",
        "started_utc": started,
        "completed_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "safety_state": "SITL only; no arming, trajectory, or physical interface",
        "container": container,
        "capture_command": command,
        "capture_returncode": capture.returncode,
        "capture_stderr": capture.stderr,
        "settle_s": settle_s,
        "spawn_status": spawn_status,
        "spawn_error": holder.get("error"),
        "topic_count": len(topics),
        "namespace_counts": {
            "sentinel": sum(name.startswith("/sentinel/") for name in topics),
            "scout": sum(name.startswith("/scout/") for name in topics),
        },
        "delivery_samples": samples,
        "delivery_passed": delivery_passed,
        "required_topic_checks": checks,
        "status": status,
        "raw_topic_list_sha256": sha256(output / "ros2_topic_list.txt"),
        "acceptance": "both namespaces expose required paths and deliver one typed vehicle-status sample while both PX4 instances are alive",
        "claim_boundary": (
            "Proves simultaneous ROS 2 graph visibility and one status sample per "
            "PX4 SITL instance. It does not prove command execution, flight, "
            "mission correctness, reliability, or physical hardware."
        ),
        "source_hashes": {
            "runner": sha256(Path(__file__)),
            "spawn_runner": sha256(root / "tools" / "run_dual_px4_spawn_probe.py"),
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": status, "topic_count": len(topics), "namespace_counts": result["namespace_counts"], "checks": checks}, indent=2))
    return result


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime", type=Path,
        default=Path("/home/sefroyek/drone_enhanced_sim/PX4-Autopilot-v1.17.0"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--container", default="drone-xrce-ros-probe")
    parser.add_argument("--duration-s", type=float, default=45.0)
    parser.add_argument("--settle-s", type=float, default=18.0)
    args = parser.parse_args()
    result = run(root, args.runtime, args.output, args.container, args.duration_s, args.settle_s)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
