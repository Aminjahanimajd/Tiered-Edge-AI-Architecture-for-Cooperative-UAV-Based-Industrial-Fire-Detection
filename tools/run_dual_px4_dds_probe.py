#!/usr/bin/env python3
"""Run a bounded dual-PX4 probe through one pinned Micro XRCE-DDS Agent."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import signal
import subprocess
import time
from pathlib import Path

import run_dual_px4_spawn_probe as spawn_probe

EXPECTED_KEYS = {"sentinel": "00000002", "scout": "00000003"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stop(process: subprocess.Popen, grace_s: float = 8.0) -> int:
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=grace_s)
    return int(process.returncode)


def analyze_agent(text: str) -> dict:
    observed = sorted(
        set(
            re.findall(
                r"create_client[^\n]*client_key:\s*0x([0-9A-Fa-f]{8})",
                text,
            )
        )
    )
    normalized = {value.lower() for value in observed}
    checks = {vehicle: key.lower() in normalized for vehicle, key in EXPECTED_KEYS.items()}
    return {"observed_client_keys": observed, "checks": checks, "passed": all(checks.values())}


def run(root: Path, runtime: Path, agent_binary: Path, output: Path, duration_s: float) -> dict:
    root, runtime, agent_binary, output = map(Path, (root, runtime, agent_binary, output))
    if output.exists():
        raise FileExistsError("output directory already exists")
    if not agent_binary.is_file():
        raise FileNotFoundError(agent_binary)
    output.mkdir(parents=True)
    log_path = output / "agent.log"
    command = [str(agent_binary), "udp4", "-p", "8888", "-v", "6"]
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    spawn_result = {"status": "NOT_RUN"}

    with log_path.open("wb") as stream:
        agent = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=stream,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            time.sleep(2.0)
            if agent.poll() is not None:
                raise RuntimeError("Micro XRCE-DDS Agent exited before PX4 launch")
            spawn_result = spawn_probe.run(root, runtime, output / "spawn", duration_s)
            time.sleep(2.0)
        finally:
            agent_returncode = stop(agent)

    analysis = analyze_agent(log_path.read_text(encoding="utf-8", errors="replace"))
    status = "PASS" if spawn_result["status"] == "PASS" and analysis["passed"] else "FAIL"
    result = {
        "schema_version": 1,
        "run_type": "dual_px4_single_xrce_agent_development_probe",
        "started_utc": started,
        "completed_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "safety_state": "SITL only; no physical interface, arming, or actuator",
        "agent": {
            "command": command,
            "binary_sha256": sha256(agent_binary),
            "returncode_after_sigint": agent_returncode,
            "log": log_path.name,
            "log_sha256": sha256(log_path),
            "analysis": analysis,
        },
        "spawn_manifest": "spawn/manifest.json",
        "spawn_status": spawn_result["status"],
        "acceptance": "both distinct PX4 DDS client keys attach to one pinned agent",
        "status": status,
        "claim_boundary": (
            "Proves two SITL PX4 clients reached one XRCE agent with distinct keys; "
            "does not prove ROS graph visibility, commands, mission behavior, or physical vehicles."
        ),
        "source_hashes": {
            "runner": sha256(Path(__file__)),
            "spawn_runner": sha256(root / "tools" / "run_dual_px4_spawn_probe.py"),
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": status, "analysis": analysis, "output": str(output)}, indent=2))
    return result


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime", type=Path,
        default=Path("/home/sefroyek/drone_enhanced_sim/PX4-Autopilot-v1.17.0"),
    )
    parser.add_argument(
        "--agent", type=Path,
        default=Path(
            "/home/sefroyek/drone_enhanced_sim/"
            "Micro-XRCE-DDS-Agent-v2.4.3/build/MicroXRCEAgent"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-s", type=float, default=15.0)
    args = parser.parse_args()
    result = run(root, args.runtime, args.agent, args.output, args.duration_s)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
