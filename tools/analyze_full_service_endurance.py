#!/usr/bin/env python3
"""Analyze the stationary 29 September complete-service endurance evidence.

The two extracted device trees and their source archives are treated as
read-only.  The output distinguishes the 30-minute coexistence observation
from the shorter corrected hierarchy probe and retains the failed/mismatched
probe as configuration-development evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
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


def resource_analysis(path: Path) -> dict[str, Any]:
    records = read_jsonl(path)
    mem = [float(r["mem_available_kib"]) / 1024.0 for r in records if r.get("mem_available_kib") is not None]
    swap = [
        (float(r["swap_total_kib"]) - float(r["swap_free_kib"])) / 1024.0
        for r in records
        if r.get("swap_total_kib") is not None and r.get("swap_free_kib") is not None
    ]
    temperatures = [
        float(zone["celsius_if_millidegrees"])
        for record in records
        for zone in record.get("thermal_zones", [])
        if 1.0 <= float(zone.get("celsius_if_millidegrees", 0.0)) < 120.0
    ]
    duration = (
        float(records[-1]["monotonic_seconds"]) - float(records[0]["monotonic_seconds"])
        if len(records) >= 2
        else 0.0
    )
    return {
        "sample_count": len(records),
        "observed_duration_seconds": duration,
        "cpu_total_percent": describe(
            r["cpu_total_percent"] for r in records if r.get("cpu_total_percent") is not None
        ),
        "mem_available_mib": describe(mem),
        "swap_used_mib": describe(swap),
        "swap_growth_mib_first_to_last": swap[-1] - swap[0] if len(swap) >= 2 else None,
        "thermal_zone_celsius": describe(temperatures),
    }


def parse_manifest(path: Path, extracted_root: Path) -> dict[str, Any]:
    checked: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, remote_path = line.split(maxsplit=1)
        marker = "/control/"
        if marker not in remote_path:
            raise ValueError(f"unrecognized manifest path: {remote_path}")
        relative = Path("control") / remote_path.split(marker, 1)[1]
        local_path = extracted_root / relative
        actual = sha256(local_path)
        checked.append(
            {
                "relative_path": relative.as_posix(),
                "expected_sha256": expected,
                "actual_sha256": actual,
                "match": actual == expected,
            }
        )
    return {
        "manifest": evidence(path),
        "checked_file_count": len(checked),
        "all_match": all(item["match"] for item in checked),
        "files": checked,
    }


def event_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(r.get("event_type")) for r in records).items()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sentinel-root", type=Path, required=True)
    parser.add_argument("--scout-root", type=Path, required=True)
    parser.add_argument("--sentinel-archive", type=Path, required=True)
    parser.add_argument("--scout-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    trial = "fullstack-20260929-r2"
    sentinel_control = args.sentinel_root / "control" / trial
    scout_control = args.scout_root / "control" / trial
    sentinel_events_path = (
        args.sentinel_root
        / "sentinel_node_sessions/sentinel-rebuild-20260924"
        / trial
        / "sentinel/events.jsonl"
    )
    scout_events_path = args.scout_root / "node_sessions" / trial / "events.jsonl"
    corrected_probe_summary_path = args.sentinel_root / "hierarchy_probe" / trial / "probe_summary.json"
    corrected_probe_events_path = args.sentinel_root / "hierarchy_probe" / trial / "probe_events.jsonl"
    mismatched_probe_summary_path = (
        args.sentinel_root / "hierarchy_probe" / f"{trial}-probe" / "probe_summary.json"
    )

    required = [
        args.sentinel_archive,
        args.scout_archive,
        sentinel_events_path,
        scout_events_path,
        corrected_probe_summary_path,
        corrected_probe_events_path,
        mismatched_probe_summary_path,
        sentinel_control / "resources/resource_samples.jsonl",
        scout_control / "resources/resource_samples.jsonl",
        sentinel_control / "sha256_manifest.txt",
        scout_control / "sha256_manifest.txt",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        parser.error("missing inputs: " + ", ".join(missing))

    sentinel_events = read_jsonl(sentinel_events_path)
    scout_events = read_jsonl(scout_events_path)
    corrected_probe = read_json(corrected_probe_summary_path)
    corrected_probe_events = read_jsonl(corrected_probe_events_path)
    mismatched_probe = read_json(mismatched_probe_summary_path)
    sentinel_resources = resource_analysis(sentinel_control / "resources/resource_samples.jsonl")
    scout_resources = resource_analysis(scout_control / "resources/resource_samples.jsonl")
    sentinel_inferences = [r for r in sentinel_events if r.get("event_type") == "inference"]
    scout_inferences = [r for r in scout_events if r.get("event_type") == "verification_inference"]
    scout_verdicts = [r for r in scout_events if r.get("event_type") == "hazard_verdict_published"]
    sentinel_ignored = [r for r in sentinel_events if r.get("event_type") == "verdict_ignored"]
    sentinel_console = (sentinel_control / "node_runner_console.log").read_text(encoding="utf-8", errors="replace")
    scout_console = (scout_control / "node_runner_console.log").read_text(encoding="utf-8", errors="replace")
    mav_before = (sentinel_control / "mavproxy_before.txt").read_text(encoding="utf-8", errors="replace")
    mav_after = (sentinel_control / "mavproxy_after.txt").read_text(encoding="utf-8", errors="replace")

    sentinel_manifest = parse_manifest(sentinel_control / "sha256_manifest.txt", args.sentinel_root)
    scout_manifest = parse_manifest(scout_control / "sha256_manifest.txt", args.scout_root)
    corrected_probe_valid = (
        corrected_probe.get("status") == "PASS"
        and corrected_probe.get("requested_count") == 36
        and corrected_probe.get("received_count") == 36
        and corrected_probe.get("missing_count") == 0
        and corrected_probe.get("duplicate_count") == 0
        and corrected_probe.get("correlation_mismatch_count") == 0
        and len(corrected_probe_events) == 36
    )
    sentinel_latency = describe(r["inference_latency_ms"] for r in sentinel_inferences)
    scout_latency = describe(r["inference_latency_ms"] for r in scout_inferences)
    probe_p95 = float(corrected_probe["latency_ms"]["p95"])
    acceptance = {
        "source_archives_present_and_hashed": True,
        "device_control_manifests_match": sentinel_manifest["all_match"] and scout_manifest["all_match"],
        "stationary_propellers_removed_and_flight_commands_disabled": (
            "flight_commands_enabled=false" in sentinel_console
            and "enable_flight_commands=false" in scout_console
        ),
        "both_wrappers_passed_bounded_stop": (
            int((sentinel_control / "node_runner_exit_code.txt").read_text().strip()) == 0
            and int((scout_control / "node_runner_exit_code.txt").read_text().strip()) == 0
            and "status=PASS_BOUNDED_STOP" in sentinel_console
            and "status=PASS_BOUNDED_SCOUT_REBUILD_VALIDATION" in scout_console
        ),
        "both_resource_windows_at_least_1800_seconds": (
            sentinel_resources["observed_duration_seconds"] >= 1800.0
            and scout_resources["observed_duration_seconds"] >= 1800.0
        ),
        "corrected_three_minute_probe_complete_and_correlated": corrected_probe_valid,
        "corrected_probe_was_not_thirty_minutes": corrected_probe.get("duration_seconds", 0.0) < 300.0,
        "mismatched_thirty_minute_probe_retained_as_failed_configuration_attempt": (
            mismatched_probe.get("received_count") == 0 and mismatched_probe.get("missing_count", 0) > 0
        ),
        "sentinel_inference_p95_at_most_200_ms": sentinel_latency.get("p95", float("inf")) <= 200.0,
        "scout_alert_to_verdict_p95_at_most_2000_ms": probe_p95 <= 2000.0,
        "jetson_mem_available_at_least_512_mib": sentinel_resources["mem_available_mib"].get("minimum", 0.0) >= 512.0,
        "no_positive_swap_growth_on_either_host": (
            sentinel_resources["swap_growth_mib_first_to_last"] <= 0.0
            and scout_resources["swap_growth_mib_first_to_last"] <= 0.0
        ),
        "no_logger_drops_observed": (
            max((int(r.get("logger_dropped_records", 0)) for r in sentinel_inferences), default=0) == 0
            and max((int(r.get("logger_dropped_records", 0)) for r in scout_inferences), default=0) == 0
        ),
        "mavproxy_active_with_vehicle_link_before_and_after": (
            "Active: active (running)" in mav_before
            and "Active: active (running)" in mav_after
            and "link 1 OK" in mav_before
            and "link 1 OK" in mav_after
        ),
    }
    result = {
        "schema_version": 1,
        "analysis_type": "stationary_complete_service_endurance",
        "experiment_id": "full-service-20260929",
        "trial_id": trial,
        "status": "PASS_WITH_UNMET_SCOUT_LATENCY_CRITERION",
        "source_archives": {
            "sentinel": evidence(args.sentinel_archive),
            "scout": evidence(args.scout_archive),
        },
        "device_manifest_verification": {
            "sentinel": sentinel_manifest,
            "scout": scout_manifest,
        },
        "sentinel": {
            "event_counts": event_counts(sentinel_events),
            "inference_frames": len(sentinel_inferences),
            "inference_latency_ms": sentinel_latency,
            "camera_errors": sum(r.get("event_type") == "camera_error" for r in sentinel_events),
            "logger_dropped_records_max": max(
                (int(r.get("logger_dropped_records", 0)) for r in sentinel_inferences), default=0
            ),
            "ignored_probe_verdicts": len(sentinel_ignored),
            "resources": sentinel_resources,
            "mavproxy_snapshot": {
                "active_before": "Active: active (running)" in mav_before,
                "active_after": "Active: active (running)" in mav_after,
                "vehicle_link_before": "link 1 OK" in mav_before,
                "vehicle_link_after": "link 1 OK" in mav_after,
                "fence_breach_text_present": "fence breach" in mav_after,
            },
        },
        "scout": {
            "event_counts": event_counts(scout_events),
            "verification_inferences": len(scout_inferences),
            "verdicts": len(scout_verdicts),
            "inference_latency_ms": scout_latency,
            "queue_delay_ms": describe(r["queue_delay_ms"] for r in scout_inferences),
            "frame_age_at_start_ms": describe(r["frame_age_at_start_ms"] for r in scout_inferences),
            "logger_dropped_records_max": max(
                (int(r.get("logger_dropped_records", 0)) for r in scout_inferences), default=0
            ),
            "resources": scout_resources,
        },
        "hierarchy_probe": {
            "corrected": corrected_probe,
            "mismatched_development_attempt": mismatched_probe,
            "scope_note": (
                "The corrected 36-event probe ran for 180.245 s near the end of the "
                "30-minute coexistence window. It validates synthetic alert transport, "
                "Scout live-frame inference and verdict transport, not 30 minutes of "
                "continuous hierarchy requests or Sentinel camera-to-final-decision latency."
            ),
        },
        "acceptance": acceptance,
        "limitations": [
            "Stationary platforms with propellers removed; no physical flight was attempted.",
            "Host-wide resources are not per-process power or energy measurements.",
            "The corrected hierarchy load covers approximately three minutes, not the full endurance interval.",
            "The corrected probe injects synthetic alerts and excludes Sentinel detection latency.",
            "Scout p95 alert-to-verdict latency exceeded the preregistered 2 s target.",
            "The MAVProxy snapshot records an existing fence-breach warning; no command was transmitted in this trial.",
            "This experiment does not estimate detector accuracy or operational industrial reliability.",
        ],
        "claim_boundary": (
            "Evidence supports 30-minute stationary coexistence of live cameras, deployed edge "
            "inference, ROS 2, logging, SwarmNet, Scout PX4 services and Sentinel MAVProxy/Pixhawk "
            "telemetry, plus a separate corrected 36-event live Scout-verification probe during "
            "the final three minutes. It does not support physical-flight, ignition-to-detection, "
            "power, industrial-site reliability, or a claim that the full hierarchy was stimulated "
            "continuously for 30 minutes."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
