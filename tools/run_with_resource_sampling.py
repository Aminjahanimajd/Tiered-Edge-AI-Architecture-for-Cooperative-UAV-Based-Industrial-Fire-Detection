#!/usr/bin/env python3
"""Run one command while retaining host and NVIDIA resource observations."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import platform
import statistics
import subprocess
import sys
import time
import traceback
from pathlib import Path


RESOURCE_FIELDS = (
    "system_cpu_percent",
    "system_ram_used_mib",
    "system_ram_percent",
    "process_tree_rss_mib",
    "gpu_utilization_percent",
    "gpu_memory_used_mib",
    "gpu_temperature_c",
    "gpu_power_w",
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite_summary(values: list[float | None]) -> dict[str, float | int | None]:
    valid = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return {
        "sample_count": len(valid),
        "mean": statistics.fmean(valid) if valid else None,
        "median": statistics.median(valid) if valid else None,
        "minimum": min(valid) if valid else None,
        "maximum": max(valid) if valid else None,
        "standard_deviation_sample": statistics.stdev(valid) if len(valid) > 1 else None,
    }


def nvidia_observation() -> dict[str, float | None]:
    command = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
        "--id=0",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=5, check=True)
        values = [value.strip() for value in completed.stdout.splitlines()[0].split(",")]
        parsed = []
        for value in values:
            try:
                parsed.append(float(value))
            except ValueError:
                parsed.append(None)
        return dict(zip(RESOURCE_FIELDS[4:], parsed))
    except (FileNotFoundError, subprocess.SubprocessError, IndexError):
        return {field: None for field in RESOURCE_FIELDS[4:]}


def process_tree_rss_mib(process) -> float | None:
    try:
        processes = [process] + process.children(recursive=True)
        return sum(item.memory_info().rss for item in processes if item.is_running()) / (1024.0 ** 2)
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=0.5)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    if arguments.command and arguments.command[0] == "--":
        arguments.command = arguments.command[1:]
    if not arguments.command:
        raise ValueError("a command is required after --")
    if arguments.interval_seconds < 0.1:
        raise ValueError("sampling interval must be at least 0.1 seconds")
    output = arguments.output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)

    try:
        import psutil
    except ImportError as exc:
        raise RuntimeError("psutil is required in the wrapper environment") from exc

    stdout_path = output / "command_stdout.log"
    stderr_path = output / "command_stderr.log"
    samples_path = output / "resource_samples.csv"
    started_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    started_monotonic = time.monotonic()
    observations: list[dict] = []
    return_code = 127
    launch_error = None
    with stdout_path.open("x", encoding="utf-8") as stdout, stderr_path.open(
        "x", encoding="utf-8"
    ) as stderr:
        try:
            child = subprocess.Popen(arguments.command, stdout=stdout, stderr=stderr)
            tracked = psutil.Process(child.pid)
            psutil.cpu_percent(interval=None)
            while child.poll() is None:
                virtual_memory = psutil.virtual_memory()
                observation = {
                    "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "monotonic_seconds": time.monotonic(),
                    "system_cpu_percent": psutil.cpu_percent(interval=None),
                    "system_ram_used_mib": virtual_memory.used / (1024.0 ** 2),
                    "system_ram_percent": virtual_memory.percent,
                    "process_tree_rss_mib": process_tree_rss_mib(tracked),
                }
                observation.update(nvidia_observation())
                observations.append(observation)
                time.sleep(arguments.interval_seconds)
            return_code = child.wait()
        except Exception as error:
            launch_error = repr(error)
            stderr.write(traceback.format_exc())

    if not observations:
        virtual_memory = psutil.virtual_memory()
        observation = {
            "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "monotonic_seconds": time.monotonic(),
            "system_cpu_percent": psutil.cpu_percent(interval=None),
            "system_ram_used_mib": virtual_memory.used / (1024.0 ** 2),
            "system_ram_percent": virtual_memory.percent,
            "process_tree_rss_mib": None,
        }
        observation.update(nvidia_observation())
        observations.append(observation)

    with samples_path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(observations[0]))
        writer.writeheader()
        writer.writerows(observations)
    summary = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "status": "completed" if return_code == 0 else "failed",
        "model_id": arguments.model_id,
        "started_utc": started_utc,
        "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "duration_seconds": time.monotonic() - started_monotonic,
        "sampling_interval_seconds": arguments.interval_seconds,
        "sample_count": len(observations),
        "return_code": return_code,
        "command": arguments.command,
        "host": platform.node(),
        "platform": platform.platform(),
        "python": sys.version,
        "metrics": {
            field: finite_summary([observation.get(field) for observation in observations])
            for field in RESOURCE_FIELDS
        },
        "evidence": {
            "resource_samples_sha256": file_sha256(samples_path),
            "stdout_sha256": file_sha256(stdout_path),
            "stderr_sha256": file_sha256(stderr_path),
            "tool_sha256": file_sha256(Path(__file__)),
        },
        "limitations": [
            "CPU and RAM are host-wide observations and require an otherwise controlled laptop workload.",
            "Process-tree RSS can under-report work executed inside WSL 2; system RAM remains the cross-framework measure.",
            "GPU samples are device-wide and may include concurrent graphics or desktop activity.",
        ],
    }
    if launch_error is not None:
        summary["launch_error"] = launch_error
    summary_path = output / "run_summary.json"
    with summary_path.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    raise SystemExit(return_code)


if __name__ == "__main__":
    main()
