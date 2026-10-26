#!/usr/bin/env python3
"""Collect portable 1 Hz resource evidence on older edge-device Python."""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import signal
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path


STOP = False


def request_stop(_signum, _frame):
    global STOP
    STOP = True


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256(path):
    digest = hashlib.sha256()
    with open(str(path), "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def key_values(path):
    values = {}
    try:
        with open(path, "r") as source:
            for line in source:
                key, separator, value = line.partition(":")
                if separator:
                    values[key.strip()] = value.strip()
    except (IOError, OSError):
        pass
    return values


def cpu_ticks():
    try:
        with open("/proc/stat", "r") as source:
            values = [int(value) for value in source.readline().split()[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values), idle
    except (IOError, OSError, ValueError, IndexError):
        return None


def parse_kib(value):
    if not value:
        return None
    try:
        return float(value.split()[0])
    except (ValueError, IndexError):
        return None


def snapshot(previous):
    memory = key_values("/proc/meminfo")
    current = cpu_ticks()
    cpu = None
    if previous is not None and current is not None:
        total_delta = current[0] - previous[0]
        idle_delta = current[1] - previous[1]
        if total_delta > 0:
            cpu = 100.0 * (total_delta - idle_delta) / total_delta
    thermal = []
    root = Path("/sys/class/thermal")
    if root.is_dir():
        for zone in sorted(root.glob("thermal_zone*")):
            try:
                sensor_type = (zone / "type").read_text().strip()
                raw = float((zone / "temp").read_text().strip())
            except (IOError, OSError, ValueError):
                continue
            thermal.append({"zone": zone.name, "type": sensor_type, "raw": raw, "celsius_if_millidegrees": raw / 1000.0})
    return ({
        "utc": utc_now(),
        "monotonic_seconds": time.monotonic(),
        "cpu_total_percent": cpu,
        "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
        "mem_total_kib": parse_kib(memory.get("MemTotal")),
        "mem_available_kib": parse_kib(memory.get("MemAvailable")),
        "swap_total_kib": parse_kib(memory.get("SwapTotal")),
        "swap_free_kib": parse_kib(memory.get("SwapFree")),
        "thermal_zones": thermal,
    }, current)


def describe(values):
    valid = [float(value) for value in values if value is not None]
    if not valid:
        return {"n": 0}
    ordered = sorted(valid)
    position = (len(ordered) - 1) * 0.95
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    p95 = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return {"n": len(valid), "mean": statistics.mean(valid), "median": statistics.median(valid), "minimum": min(valid), "maximum": max(valid), "p95": p95, "population_standard_deviation": statistics.pstdev(valid)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--maximum-duration-seconds", type=float, default=3660.0)
    args = parser.parse_args()
    if args.output_directory.exists():
        parser.error("output directory exists; collection is non-overwriting")
    if args.interval_seconds <= 0 or args.maximum_duration_seconds <= 0:
        parser.error("durations must be positive")
    args.output_directory.mkdir(parents=True)
    samples_path = args.output_directory / "resource_samples.jsonl"
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    started_utc = utc_now()
    started = time.monotonic()
    previous = None
    samples = []
    with samples_path.open("x", encoding="utf-8") as destination:
        while not STOP and time.monotonic() - started < args.maximum_duration_seconds:
            sample, previous = snapshot(previous)
            samples.append(sample)
            destination.write(json.dumps(sample, sort_keys=True) + "\n")
            destination.flush()
            deadline = time.monotonic() + args.interval_seconds
            while not STOP and time.monotonic() < deadline:
                time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
    temperatures = [float(zone["celsius_if_millidegrees"]) for sample in samples for zone in sample["thermal_zones"] if 0 < float(zone["celsius_if_millidegrees"]) < 120]
    summary = {
        "schema_version": 1,
        "status": "PASS" if samples else "FAIL",
        "platform": args.platform,
        "started_utc": started_utc,
        "finished_utc": utc_now(),
        "duration_seconds": time.monotonic() - started,
        "sampling_interval_seconds": args.interval_seconds,
        "sample_count": len(samples),
        "metrics": {
            "cpu_total_percent": describe([sample["cpu_total_percent"] for sample in samples]),
            "mem_available_mib": describe([sample["mem_available_kib"] / 1024.0 if sample["mem_available_kib"] is not None else None for sample in samples]),
            "swap_used_mib": describe([(sample["swap_total_kib"] - sample["swap_free_kib"]) / 1024.0 if sample["swap_total_kib"] is not None and sample["swap_free_kib"] is not None else None for sample in samples]),
            "valid_thermal_zone_celsius": describe(temperatures),
        },
        "samples_sha256": sha256(samples_path),
        "claim_boundary": "Host-wide 1 Hz resource observations during a separately logged stationary full-service run; not process attribution, power, energy, flight, or industrial reliability.",
    }
    summary_path = args.output_directory / "resource_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
