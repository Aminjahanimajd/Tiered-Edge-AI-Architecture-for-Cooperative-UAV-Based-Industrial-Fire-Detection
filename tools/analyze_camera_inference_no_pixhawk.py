#!/usr/bin/env python3
"""Analyze a paired, stationary camera/inference run without the Pixhawk.

Raw inputs are read-only. The script writes one derived JSON document and does
not infer flight-controller, power, industrial-reliability, or accuracy claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any, Iterable


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
    return records


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def describe(values: Iterable[float]) -> dict[str, Any]:
    valid = [float(value) for value in values]
    if not valid:
        return {"n": 0}
    return {
        "n": len(valid),
        "mean": statistics.mean(valid),
        "median": statistics.median(valid),
        "minimum": min(valid),
        "maximum": max(valid),
        "p95": percentile(valid, 0.95),
        "population_standard_deviation": statistics.pstdev(valid),
    }


def evidence(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "sha256": sha256(path)}


def events_of(records: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [record for record in records if record.get("event_type") == event_type]


def resource_analysis(path: Path) -> dict[str, Any]:
    records = read_jsonl(path)
    mem = [record.get("mem_available_kib") for record in records]
    swap = [
        record["swap_total_kib"] - record["swap_free_kib"]
        for record in records
        if record.get("swap_total_kib") is not None
        and record.get("swap_free_kib") is not None
    ]
    temperatures = [
        float(zone["celsius_if_millidegrees"])
        for record in records
        for zone in record.get("thermal_zones", [])
        if 0.0 < float(zone.get("celsius_if_millidegrees", 0.0)) < 120.0
    ]
    duration = (
        records[-1]["monotonic_seconds"] - records[0]["monotonic_seconds"]
        if len(records) >= 2
        else 0.0
    )
    return {
        "sample_count": len(records),
        "observed_duration_seconds": duration,
        "cpu_total_percent": describe(
            record["cpu_total_percent"]
            for record in records
            if record.get("cpu_total_percent") is not None
        ),
        "mem_available_mib": describe(value / 1024.0 for value in mem if value is not None),
        "swap_used_mib": describe(value / 1024.0 for value in swap),
        "swap_growth_mib_first_to_last": (
            (swap[-1] - swap[0]) / 1024.0 if len(swap) >= 2 else None
        ),
        "thermal_zone_celsius": describe(temperatures),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--probe-summary", type=Path, required=True)
    parser.add_argument("--probe-events", type=Path, required=True)
    parser.add_argument("--sentinel-events", type=Path, required=True)
    parser.add_argument("--scout-events", type=Path, required=True)
    parser.add_argument("--sentinel-resources", type=Path, required=True)
    parser.add_argument("--scout-resources", type=Path, required=True)
    parser.add_argument("--sentinel-exit-code", type=Path, required=True)
    parser.add_argument("--scout-exit-code", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    for path in (
        args.probe_summary,
        args.probe_events,
        args.sentinel_events,
        args.scout_events,
        args.sentinel_resources,
        args.scout_resources,
        args.sentinel_exit_code,
        args.scout_exit_code,
    ):
        if not path.is_file():
            parser.error(f"missing input: {path}")

    probe = read_json(args.probe_summary)
    probe_records = read_jsonl(args.probe_events)
    sentinel = read_jsonl(args.sentinel_events)
    scout = read_jsonl(args.scout_events)
    sentinel_inferences = events_of(sentinel, "inference")
    scout_inferences = events_of(scout, "verification_inference")
    scout_verdicts = events_of(scout, "hazard_verdict_published")
    stale_verdicts = [record for record in scout_verdicts if record.get("reason") == "stale_frame"]
    error_verdicts = [record for record in scout_verdicts if record.get("verdict") == "ERROR"]
    sentinel_resource = resource_analysis(args.sentinel_resources)
    scout_resource = resource_analysis(args.scout_resources)
    sentinel_exit = int(args.sentinel_exit_code.read_text(encoding="utf-8").strip())
    scout_exit = int(args.scout_exit_code.read_text(encoding="utf-8").strip())

    scout_latency_p95 = probe.get("latency_ms", {}).get("p95")
    jetson_mem_min = sentinel_resource["mem_available_mib"].get("minimum")
    result = {
        "schema_version": 1,
        "analysis_type": "stationary_camera_inference_no_pixhawk",
        "trial_id": args.trial_id,
        "raw_evidence": {
            name: evidence(path)
            for name, path in {
                "probe_summary": args.probe_summary,
                "probe_events": args.probe_events,
                "sentinel_events": args.sentinel_events,
                "scout_events": args.scout_events,
                "sentinel_resources": args.sentinel_resources,
                "scout_resources": args.scout_resources,
                "sentinel_exit_code": args.sentinel_exit_code,
                "scout_exit_code": args.scout_exit_code,
            }.items()
        },
        "probe": probe,
        "sentinel": {
            "node_exit_code": sentinel_exit,
            "inference_frames": len(sentinel_inferences),
            "inference_latency_ms": describe(
                record["inference_latency_ms"] for record in sentinel_inferences
            ),
            "camera_errors": len(events_of(sentinel, "camera_error")),
            "logger_dropped_records_max": max(
                (int(record.get("logger_dropped_records", 0)) for record in sentinel_inferences),
                default=0,
            ),
            "resources": sentinel_resource,
        },
        "scout": {
            "node_exit_code": scout_exit,
            "alerts_received": len(events_of(scout, "hazard_alert_received")),
            "verification_inferences": len(scout_inferences),
            "verdicts": len(scout_verdicts),
            "stale_frame_verdicts": len(stale_verdicts),
            "error_verdicts": len(error_verdicts),
            "inference_latency_ms": describe(
                record["inference_latency_ms"] for record in scout_inferences
            ),
            "frame_age_at_start_ms": describe(
                record["frame_age_at_start_ms"] for record in scout_inferences
            ),
            "queue_delay_ms": describe(
                record["queue_delay_ms"] for record in scout_inferences
            ),
            "logger_dropped_records_max": max(
                (int(record.get("logger_dropped_records", 0)) for record in scout_inferences),
                default=0,
            ),
            "resources": scout_resource,
        },
        "acceptance": {
            "probe_complete_and_correlated": (
                probe.get("status") == "PASS"
                and probe.get("missing_count") == 0
                and probe.get("correlation_mismatch_count") == 0
                and probe.get("duplicate_count") == 0
                and len(probe_records) == probe.get("requested_count")
            ),
            "fresh_scout_frame_for_every_verdict": (
                len(stale_verdicts) == 0
                and len(error_verdicts) == 0
                and len(scout_inferences) == len(probe_records)
            ),
            "nodes_stopped_cleanly": sentinel_exit == 0 and scout_exit == 0,
            "sentinel_mem_available_at_least_512_mib": (
                jetson_mem_min is not None and jetson_mem_min >= 512.0
            ),
            "scout_p95_alert_to_verdict_at_most_2000_ms": (
                scout_latency_p95 is not None and scout_latency_p95 <= 2000.0
            ),
        },
        "claim_boundary": (
            "This run evaluates stationary live cameras, edge inference, ROS 2 transport, "
            "logging, and host-wide resources with the Sentinel Pixhawk unpowered. It is "
            "not complete-stack endurance, physical flight, ignition-to-detection latency, "
            "power/energy measurement, detector accuracy, or industrial reliability."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
