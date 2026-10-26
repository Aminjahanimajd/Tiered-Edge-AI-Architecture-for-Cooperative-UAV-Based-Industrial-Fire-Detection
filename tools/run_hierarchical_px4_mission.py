#!/usr/bin/env python3
"""Orchestrate one evidence-complete hierarchical PX4/Gazebo development run."""

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
import capture_gazebo_native_video as visual_capture


REQUIRED_TOPICS = (
    "/sentinel/fmu/in/offboard_control_mode",
    "/sentinel/fmu/in/trajectory_setpoint",
    "/sentinel/fmu/in/vehicle_command",
    "/sentinel/fmu/out/vehicle_status_v1",
    "/sentinel/fmu/out/vehicle_local_position_v1",
    "/scout/fmu/in/offboard_control_mode",
    "/scout/fmu/in/trajectory_setpoint",
    "/scout/fmu/in/vehicle_command",
    "/scout/fmu/out/vehicle_status_v1",
    "/scout/fmu/out/vehicle_local_position_v1",
)


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
        if isinstance(value, dict) and value.get("status") in {
            "PASS", "FAIL", "RESTART_REQUIRED"
        }:
            results.append(value)
    if not results:
        raise ValueError("mission stdout contains no status result")
    return results[-1]


def container_mission_command(
    container, root, scenario, event_id, event_log, timeout_s, fault="none",
    runner_mode="single_event", recovery_only=False, landing_timeout_s=30.0,
):
    relative_scenario = scenario.relative_to(root).as_posix()
    relative_log = event_log.relative_to(root).as_posix()
    shell = (
        "source /opt/ros/jazzy/setup.bash && "
        "source /ws/install/setup.bash && "
        "export PYTHONPATH=/project/src:${PYTHONPATH:-} && "
        "export DRONE_ENHANCED_SIMULATION_ONLY="
        "I_ACKNOWLEDGE_PX4_SITL_ONLY && "
        "python3 /project/tools/px4_sim_hierarchical_mission.py "
        f"--scenario /project/{relative_scenario} "
        f"--event-id {event_id} "
        f"--output /project/{relative_log} "
        f"--total-timeout-s {float(timeout_s)} "
        f"--landing-timeout-s {float(landing_timeout_s)} "
        f"--fault {fault} "
        f"--runner-mode {runner_mode}"
        + (" --recovery-only" if recovery_only else "")
    )
    return ["docker.exe", "exec", container, "bash", "-lc", shell]


def wait_for_required_topics(command, required, timeout_s=60.0, interval_s=2.0):
    deadline = time.monotonic() + timeout_s
    attempts = []
    while True:
        completed = subprocess.run(
            command, text=True, capture_output=True, timeout=25
        )
        checks = {topic: topic in completed.stdout for topic in required}
        attempts.append({
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "checks": checks,
            "monotonic_ns": time.monotonic_ns(),
        })
        if completed.returncode == 0 and all(checks.values()):
            return completed, checks, attempts
        if time.monotonic() >= deadline:
            return completed, checks, attempts
        time.sleep(interval_s)


def execute_mission(command, stdout_path, stderr_path, timeout_s):
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout_s + 45,
    )
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    try:
        result = parse_result(completed.stdout)
    except ValueError as exc:
        result = {"status": "FAIL", "failure_reason": str(exc)}
    return completed, result


def run(
    root,
    runtime,
    output,
    scenario,
    event_id,
    container,
    agent_ip,
    timeout_s=420.0,
    settle_s=18.0,
    fault="none",
    runner_mode="single_event",
    with_gui=False,
    capture_fps=0.0,
    landing_timeout_s=30.0,
):
    root = Path(root).resolve()
    runtime = Path(runtime).resolve()
    scenario = Path(scenario).resolve()
    output = Path(output)
    output = (root / output).resolve() if not output.is_absolute() else output.resolve()
    if output.exists():
        raise FileExistsError(output)
    if root not in scenario.parents:
        raise ValueError("scenario must be inside the project root")
    if root not in output.parents:
        raise ValueError("output must be inside the project root")
    if timeout_s < 180:
        raise ValueError("timeout_s must be at least 180 seconds")
    output.mkdir(parents=True)
    is_restart_fault = fault == "mission_node_restart"
    event_log = output / (
        "mission_events_before_restart.jsonl"
        if is_restart_fault else "mission_events.jsonl"
    )
    mission_command = container_mission_command(
        container, root, scenario, event_id, event_log, timeout_s, fault,
        runner_mode, landing_timeout_s=landing_timeout_s,
    )
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    holder = {}
    stop_event = threading.Event()

    def launch():
        try:
            holder["spawn"] = spawn_probe.run(
                root,
                runtime,
                output / "spawn",
                timeout_s + settle_s + 30,
                agent_ip,
                stop_event,
                not with_gui,
            )
        except BaseException as exc:
            holder["spawn_error"] = repr(exc)

    thread = threading.Thread(target=launch, daemon=False)
    thread.start()
    capture_requested = bool(with_gui and float(capture_fps) > 0)
    capture_stop = threading.Event()
    capture_ready = threading.Event()
    capture_holder = {}
    capture_thread = None
    if capture_requested:
        def capture_visuals():
            try:
                capture_holder["manifest"] = visual_capture.capture_until_stop(
                    output / "visual_capture",
                    float(capture_fps),
                    capture_stop,
                    event_log,
                    ready_event=capture_ready,
                )
            except BaseException as exc:
                capture_holder["error"] = repr(exc)

        capture_thread = threading.Thread(target=capture_visuals, daemon=False)
        capture_thread.start()
    time.sleep(settle_s)
    if capture_requested and not capture_ready.wait(timeout=90.0):
        capture_stop.set()
        stop_event.set()
        if capture_thread is not None:
            capture_thread.join(timeout=15)
        thread.join(timeout=15)
        raise TimeoutError(
            "Gazebo-native recorder did not capture a preflight frame"
        )

    topic_command = [
        "docker.exe", "exec", container, "bash", "-lc",
        "source /opt/ros/jazzy/setup.bash && "
        "source /ws/install/setup.bash && ros2 topic list -t",
    ]
    topics, topic_checks, topic_attempts = wait_for_required_topics(
        topic_command, REQUIRED_TOPICS, timeout_s=60.0, interval_s=2.0
    )
    topic_stdout = output / "ros2_topic_list.txt"
    topic_stderr = output / "ros2_topic_list.stderr.txt"
    topic_stdout.write_text(topics.stdout, encoding="utf-8")
    topic_stderr.write_text(topics.stderr, encoding="utf-8")
    (output / "ros2_topic_readiness_attempts.json").write_text(
        json.dumps(topic_attempts, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    stdout_path = output / (
        "mission_before_restart.stdout.txt"
        if is_restart_fault else "mission.stdout.txt"
    )
    stderr_path = output / (
        "mission_before_restart.stderr.txt"
        if is_restart_fault else "mission.stderr.txt"
    )
    completed, mission_result = execute_mission(
        mission_command, stdout_path, stderr_path, timeout_s
    )
    recovery_command = None
    recovery_completed = None
    recovery_result = None
    recovery_log = None
    recovery_stdout = None
    recovery_stderr = None
    if (
        is_restart_fault
        and completed.returncode == 75
        and mission_result.get("status") == "RESTART_REQUIRED"
        and mission_result.get("fault_triggered") is True
    ):
        recovery_log = output / "mission_events_after_restart.jsonl"
        recovery_command = container_mission_command(
            container,
            root,
            scenario,
            event_id,
            recovery_log,
            timeout_s,
            "none",
            "single_event",
            recovery_only=True,
            landing_timeout_s=landing_timeout_s,
        )
        recovery_stdout = output / "mission_after_restart.stdout.txt"
        recovery_stderr = output / "mission_after_restart.stderr.txt"
        recovery_completed, recovery_result = execute_mission(
            recovery_command, recovery_stdout, recovery_stderr, timeout_s
        )

    if capture_thread is not None:
        time.sleep(2.0)
        capture_stop.set()
        capture_thread.join(timeout=300)
        if capture_thread.is_alive():
            capture_holder["error"] = "visual-capture thread did not terminate"
    stop_event.set()
    thread.join(timeout=40)
    if thread.is_alive():
        raise TimeoutError("dual-PX4 spawn did not terminate")
    spawn_status = holder.get("spawn", {}).get("status", "ERROR")
    common_pass = (
        topics.returncode == 0
        and all(topic_checks.values())
        and spawn_status == "PASS"
        and (
            not capture_requested
            or capture_holder.get("manifest", {}).get("status") == "PASS"
        )
    )
    if is_restart_fault:
        mission_pass = (
            completed.returncode == 75
            and mission_result.get("status") == "RESTART_REQUIRED"
            and mission_result.get("injected_fault") == fault
            and mission_result.get("fault_triggered") is True
            and recovery_completed is not None
            and recovery_completed.returncode == 0
            and recovery_result.get("status") == "PASS"
            and recovery_result.get("recovery_only") is True
            and recovery_result.get("mission_states") == {
                "sentinel": "LANDED", "scout": "LANDED"
            }
        )
    else:
        mission_pass = (
            completed.returncode == 0
            and mission_result.get("status") == "PASS"
            and mission_result.get("injected_fault") == fault
            and (fault == "none" or mission_result.get("fault_triggered") is True)
        )
    status = "PASS" if common_pass and mission_pass else "FAIL"
    manifest = {
        "schema_version": 1,
        "run_type": "dual_px4_hierarchical_development_mission",
        "started_utc": started,
        "completed_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": status,
        "event_id": event_id,
        "injected_fault": fault,
        "runner_mode": runner_mode,
        "scenario": str(scenario),
        "safety_state": (
            "PX4/Gazebo SITL only; mandatory simulator token; no physical "
            "transport, interface, actuator, or vehicle"
        ),
        "container": container,
        "agent_ip": agent_ip,
        "gazebo_gui_requested": bool(with_gui),
        "visual_capture_requested": capture_requested,
        "visual_capture_fps": float(capture_fps),
        "landing_timeout_s": float(landing_timeout_s),
        "visual_capture_status": capture_holder.get("manifest", {}).get("status"),
        "visual_capture_error": capture_holder.get("error"),
        "visual_capture_manifest_sha256": (
            sha256(output / "visual_capture" / "manifest.json")
            if (output / "visual_capture" / "manifest.json").is_file()
            else None
        ),
        "visual_source_video_sha256": capture_holder.get(
            "manifest", {}
        ).get("source_video_sha256"),
        "visual_annotated_video_sha256": capture_holder.get(
            "manifest", {}
        ).get("annotated_video_sha256"),
        "spawn_status": spawn_status,
        "spawn_error": holder.get("spawn_error"),
        "topic_checks": topic_checks,
        "topic_readiness_attempt_count": len(topic_attempts),
        "topic_command": topic_command,
        "mission_command": mission_command,
        "mission_returncode": completed.returncode,
        "mission_result": mission_result,
        "recovery_command": recovery_command,
        "recovery_returncode": (
            recovery_completed.returncode if recovery_completed else None
        ),
        "recovery_result": recovery_result,
        "acceptance": (
            "both identities and namespaces remain isolated; Sentinel patrols "
            "and holds; Scout dispatches to standoff; the preregistered verdict "
            "drives the correct mission branch; all active vehicles return, "
            "land, disarm, and finish in typed LANDED states"
        ),
        "claim_boundary": (
            "One development run on provisional simulation proxies. It is not "
            "a formal reliability estimate, physical flight, industrial-site "
            "validation, or vision-derived localization evidence."
        ),
        "raw_hashes": {
            "event_log_sha256": sha256(event_log) if event_log.is_file() else None,
            "stdout_sha256": sha256(stdout_path),
            "stderr_sha256": sha256(stderr_path),
            "recovery_event_log_sha256": (
                sha256(recovery_log) if recovery_log and recovery_log.is_file() else None
            ),
            "recovery_stdout_sha256": (
                sha256(recovery_stdout)
                if recovery_stdout and recovery_stdout.is_file() else None
            ),
            "recovery_stderr_sha256": (
                sha256(recovery_stderr)
                if recovery_stderr and recovery_stderr.is_file() else None
            ),
            "topic_stdout_sha256": sha256(topic_stdout),
            "topic_stderr_sha256": sha256(topic_stderr),
            "topic_readiness_attempts_sha256": sha256(
                output / "ros2_topic_readiness_attempts.json"
            ),
        },
        "source_hashes": {
            "orchestrator_sha256": sha256(Path(__file__)),
            "mission_node_sha256": sha256(
                root / "tools/px4_sim_hierarchical_mission.py"
            ),
            "mission_controller_sha256": sha256(
                root / "src/drone_enhanced_core/aerial_mission.py"
            ),
            "mission_plan_sha256": sha256(
                root / "src/drone_enhanced_core/simulation_mission_plan.py"
            ),
            "px4_adapter_sha256": sha256(
                root / "src/drone_enhanced_core/px4_sim_adapter.py"
            ),
            "scenario_sha256": sha256(scenario),
            "spawn_runner_sha256": sha256(
                root / "tools/run_dual_px4_spawn_probe.py"
            ),
            "visual_capture_runner_sha256": sha256(
                root / "tools/capture_gazebo_native_video.py"
            ),
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": status,
        "spawn_status": spawn_status,
        "topic_checks": topic_checks,
        "mission_result": mission_result,
        "recovery_result": recovery_result,
        "output": str(output),
    }, indent=2, sort_keys=True))
    return manifest


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime",
        type=Path,
        default=Path(
            "/home/sefroyek/drone_enhanced_sim/PX4-Autopilot-v1.17.0"
        ),
    )
    parser.add_argument("--with-gui", action="store_true")
    parser.add_argument(
        "--capture-fps",
        type=float,
        default=0.0,
        help="capture Gazebo-native frames for the entire GUI mission",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--scenario",
        type=Path,
        default=root / "config/simulation_scenarios_v2.json",
    )
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--container", default="drone-xrce-ros-probe")
    parser.add_argument("--agent-ip", required=True)
    parser.add_argument("--timeout-s", type=float, default=420.0)
    parser.add_argument("--settle-s", type=float, default=18.0)
    parser.add_argument(
        "--landing-timeout-s",
        type=float,
        default=30.0,
        help="bounded SITL landing allowance; recorded in the run manifest",
    )
    parser.add_argument(
        "--fault",
        choices=(
            "none",
            "lost_alert",
            "delayed_verdict",
            "scout_unavailable",
            "low_battery",
            "sensor_or_inference_error",
            "duplicate_or_stale_verdict",
            "invalid_or_out_of_geofence_target",
            "mission_node_restart",
        ),
        default="none",
    )
    parser.add_argument(
        "--runner-mode",
        choices=("single_event", "repeated_confounder"),
        default="single_event",
    )
    args = parser.parse_args()
    result = run(
        root,
        args.runtime,
        args.output,
        args.scenario,
        args.event_id,
        args.container,
        args.agent_ip,
        args.timeout_s,
        args.settle_s,
        args.fault,
        args.runner_mode,
        args.with_gui,
        args.capture_fps,
        args.landing_timeout_s,
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
