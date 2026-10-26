#!/usr/bin/env python3
"""Run a bounded, headless, non-arming dual-PX4 development spawn probe."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import ipaddress
import json
import os
import signal
import subprocess
import time
from pathlib import Path

EXPECTED = {
    "sentinel": {"instance": 1, "model": "x500_v2_sentinel_proxy_1", "namespace": "sentinel", "mavlink_system_id": 2, "dds_key": 2, "pose": "0,0,0"},
    "scout": {"instance": 2, "model": "modalai_devkit_scout_proxy_2", "namespace": "scout", "mavlink_system_id": 3, "dds_key": 3, "pose": "-4,0,0"},
}
WORLD = "industrial_inspection_proxy_v1"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def analyze_log(vehicle, text):
    row = EXPECTED[vehicle]
    checks = {
        "instance": "instance: {}".format(row["instance"]) in text,
        "world": "world: {}".format(WORLD) in text,
        "model": "model: {}".format(row["model"]) in text,
        "startup": "Startup script returned successfully" in text,
        "dds_agent_endpoint": "port:8888" in text,
    }
    return {"checks": checks, "passed": all(checks.values())}


def launch_environment(vehicle, headless=True):
    row = EXPECTED[vehicle]
    values = os.environ.copy()
    values.update({
        "PX4_SYS_AUTOSTART": "4001",
        "PX4_SIM_MODEL": "gz_" + row["model"].rsplit("_", 1)[0],
        "PX4_GZ_WORLD": WORLD,
        "PX4_GZ_MODEL_POSE": row["pose"],
        "PX4_UXRCE_DDS_NS": row["namespace"],
        "PX4_UXRCE_DDS_PORT": "8888",
    })
    if headless:
        values["HEADLESS"] = "1"
    else:
        values.pop("HEADLESS", None)
    if vehicle == "scout":
        values["PX4_GZ_STANDALONE"] = "1"
    return values


def launch_command(runtime, vehicle):
    row = EXPECTED[vehicle]
    binary = runtime / "build" / "px4_sitl_default" / "bin" / "px4"
    working_directory = (
        runtime / "build" / "px4_sitl_default" / "rootfs" / str(row["instance"])
    )
    if not working_directory.is_dir():
        raise FileNotFoundError(working_directory)
    return [
        str(binary), "-d", "-i", str(row["instance"]),
        "-w", str(working_directory),
    ]


def wait_for_marker(process, log_path, marker, timeout_s=30.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if log_path.is_file() and marker in log_path.read_text(
            encoding="utf-8", errors="replace"
        ):
            return True
        if process.poll() is not None:
            return False
        time.sleep(0.25)
    return False


def wait_for_duration(duration_s, stop_event=None):
    if stop_event is None:
        time.sleep(duration_s)
        return "duration_elapsed"
    return "cancelled" if stop_event.wait(duration_s) else "duration_elapsed"


def stop_group(process, grace_s=8.0):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGINT)
        try:
            process.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=grace_s)
    return int(process.returncode)


def route_xrce_clients(runtime, agent_ip):
    agent_ip = str(ipaddress.ip_address(agent_ip))
    executable = (
        runtime / "build" / "px4_sitl_default" / "bin" / "px4-uxrce_dds_client"
    )
    parameter_executable = (
        runtime / "build" / "px4_sitl_default" / "bin" / "px4-param"
    )
    records = {}
    for vehicle in ("sentinel", "scout"):
        row = EXPECTED[vehicle]
        commands = [
            [str(executable), "--instance", str(row["instance"]), "stop"],
            [
                str(executable), "--instance", str(row["instance"]),
                "start", "-t", "udp", "-h", agent_ip, "-p", "8888",
                "-n", row["namespace"],
            ],
            [
                str(parameter_executable), "--instance", str(row["instance"]),
                "set", "NAV_DLL_ACT", "0",
            ],
            [
                str(parameter_executable), "--instance", str(row["instance"]),
                "set", "COM_RCL_EXCEPT", "4",
            ],
            [
                str(parameter_executable), "--instance", str(row["instance"]),
                "show", "NAV_DLL_ACT",
            ],
            [
                str(parameter_executable), "--instance", str(row["instance"]),
                "show", "COM_RCL_EXCEPT",
            ],
        ]
        executions = []
        for command_index, command in enumerate(commands):
            try:
                completed = subprocess.run(
                    command, cwd=runtime, text=True, capture_output=True,
                    timeout=10,
                )
                executions.append({
                    "command": command,
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                    "timed_out": False,
                })
            except subprocess.TimeoutExpired as exc:
                executions.append({
                    "command": command,
                    "returncode": None,
                    "stdout": exc.stdout or "",
                    "stderr": exc.stderr or "",
                    "timed_out": True,
                })
                # A stop request can time out while the startup client is
                # disconnected from its original endpoint.  Continue to the
                # explicit start command and let that result decide whether a
                # usable routed client exists.  Any later timeout remains a
                # hard failure through the checks below.
                if command_index != 0:
                    break
        records[vehicle] = {
            "agent_ip": agent_ip,
            "executions": executions,
            "stop_disposition": (
                "CLEAN_STOP" if executions[0]["returncode"] == 0
                else "FORCED_STOP_AFTER_TIMEOUT"
            ),
            "passed": (
                len(executions) == len(commands)
                and (executions[0]["returncode"] in {0, 255} or executions[0]["timed_out"])
                and all(item["returncode"] == 0 for item in executions[1:])
                and "NAV_DLL_ACT" in executions[4]["stdout"]
                and "COM_RCL_EXCEPT" in executions[5]["stdout"]
            ),
            "sitl_policy_reason": (
                "NAV_DLL_ACT=0 disables the simulated GCS-loss failsafe; "
                "COM_RCL_EXCEPT=4 exempts Offboard mode from simulated "
                "manual-control loss. These values apply only to isolated SITL."
            ),
        }
    return records


def run(
    root, runtime, output, duration_s, agent_ip=None, stop_event=None,
    headless=True,
):
    if duration_s < 5:
        raise ValueError("duration_s must be at least 5 seconds")
    root, runtime, output = Path(root), Path(runtime), Path(output)
    if output.exists():
        raise FileExistsError("output directory already exists")
    binary = runtime / "build" / "px4_sitl_default" / "bin" / "px4"
    if not binary.is_file():
        raise FileNotFoundError(binary)
    output.mkdir(parents=True)
    records, processes, handles = {}, {}, {}
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        for vehicle in ("sentinel", "scout"):
            log_path = output / (vehicle + ".log")
            handles[vehicle] = log_path.open("wb")
            command = launch_command(runtime, vehicle)
            processes[vehicle] = subprocess.Popen(
                command, cwd=runtime, env=launch_environment(vehicle, headless),
                stdin=subprocess.PIPE, stdout=handles[vehicle],
                stderr=subprocess.STDOUT, start_new_session=True,
            )
            chosen = launch_environment(vehicle, headless)
            records[vehicle] = {
                "command": command,
                "launch_environment": {key: chosen[key] for key in (
                    "HEADLESS", "PX4_SYS_AUTOSTART", "PX4_SIM_MODEL",
                    "PX4_GZ_WORLD", "PX4_GZ_MODEL_POSE",
                    "PX4_UXRCE_DDS_NS", "PX4_UXRCE_DDS_PORT") if key in chosen},
                "pid": processes[vehicle].pid,
                "log": log_path.name,
            }
            if vehicle == "sentinel":
                if not wait_for_marker(
                    processes[vehicle], log_path,
                    "Startup script returned successfully", timeout_s=30.0,
                ):
                    break
            else:
                wait_for_marker(
                    processes[vehicle], log_path,
                    "Startup script returned successfully", timeout_s=30.0,
                )
        if len(processes) == 2 and agent_ip:
            time.sleep(5.0)
            route_records = route_xrce_clients(runtime, agent_ip)
            for vehicle, route_record in route_records.items():
                records[vehicle]["xrce_route"] = route_record
        stop_reason = wait_for_duration(duration_s, stop_event)
    finally:
        for vehicle in ("scout", "sentinel"):
            if vehicle in processes:
                records[vehicle]["returncode"] = stop_group(processes[vehicle])
                if processes[vehicle].stdin is not None:
                    processes[vehicle].stdin.close()
        for handle in handles.values():
            handle.close()

    analyses = {}
    for vehicle in ("sentinel", "scout"):
        log_path = output / (vehicle + ".log")
        analyses[vehicle] = analyze_log(
            vehicle, log_path.read_text(encoding="utf-8", errors="replace")
        ) if log_path.is_file() else {"checks": {}, "passed": False}
        records.setdefault(vehicle, {})["analysis"] = analyses[vehicle]
        if log_path.is_file():
            records[vehicle]["log_sha256"] = sha256(log_path)

    result = {
        "schema_version": 1,
        "run_type": "dual_px4_gazebo_development_spawn_probe",
        "started_utc": started,
        "completed_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "duration_after_second_launch_s": duration_s,
        "stop_reason": stop_reason,
        "safety_state": "SITL only; PX4 daemon mode in isolated process groups; no physical interface or hardware actuator",
        "runtime": str(runtime),
        "px4_binary_sha256": sha256(binary),
        "world": WORLD,
        "vehicles": records,
        "acceptance": "both PX4 instances attach to expected distinct models and complete startup",
        "status": "PASS" if (
            all(row["passed"] for row in analyses.values())
            and all(record.get("xrce_route", {}).get("passed", True) for record in records.values())
        ) else "FAIL",
        "claim_boundary": "Development spawn only; no arming, takeoff, ROS 2 exchange, mission command, detector, or physical vehicle.",
        "source_hashes": {
            "runner": sha256(Path(__file__)),
            "scenario": sha256(root / "config" / "simulation_scenarios_v1.json"),
            "launch_contract": sha256(root / "simulation" / "development_launch_contract_v1.json"),
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": result["status"], "output": str(output), "analyses": analyses}, indent=2, sort_keys=True))
    return result


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=Path("/home/sefroyek/drone_enhanced_sim/PX4-Autopilot-v1.17.0"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-s", type=float, default=12.0)
    parser.add_argument("--agent-ip")
    parser.add_argument("--with-gui", action="store_true")
    args = parser.parse_args()
    return 0 if run(
        root, args.runtime, args.output, args.duration_s, args.agent_ip,
        headless=not args.with_gui,
    )["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
