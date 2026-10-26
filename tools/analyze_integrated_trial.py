#!/usr/bin/env python3
"""Recompute descriptive metrics for one integrated hardware trial.

The script reads immutable JSONL evidence and writes a derived JSON document.
It never edits raw evidence and intentionally avoids population-level accuracy
claims from the small, condition-specific laboratory samples.
"""

from __future__ import print_function

import argparse
import datetime as dt
import hashlib
import json
import os
import statistics


def read_jsonl(path):
    records = []
    with open(path, "r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError as error:
                raise ValueError("{}:{} invalid JSON: {}".format(path, line_number, error))
    return records


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while True:
            block = source.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def utc(value):
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return dt.datetime.fromisoformat(value)


def summary(values):
    values = [float(value) for value in values]
    if not values:
        return None
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
        "population_standard_deviation": statistics.pstdev(values),
    }


def events_of(records, event_type):
    return [record for record in records if record.get("event_type") == event_type]


def identity_check(event_groups):
    sets = {
        name: set(record.get("event_id") for record in records if record.get("event_id"))
        for name, records in event_groups.items()
    }
    all_ids = set().union(*sets.values()) if sets else set()
    return {
        "unique_event_ids": len(all_ids),
        "counts": {name: len(values) for name, values in sorted(sets.items())},
        "missing_by_group": {
            name: sorted(all_ids - values) for name, values in sorted(sets.items())
        },
        "all_groups_match": all(values == all_ids for values in sets.values()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--scout-events", required=True)
    parser.add_argument("--sentinel-events")
    parser.add_argument("--ground-truth")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()

    scout = read_jsonl(arguments.scout_events)
    verifications = events_of(scout, "verification_inference")
    scout_alerts = events_of(scout, "hazard_alert_received")
    verdicts = events_of(scout, "hazard_verdict_published")
    result = {
        "schema_version": 1,
        "trial_id": arguments.trial_id,
        "analysis_type": "descriptive_integrated_hardware_trial",
        "raw_evidence": {
            "scout_events": {
                "path": os.path.abspath(arguments.scout_events),
                "sha256": sha256(arguments.scout_events),
                "records": len(scout),
            }
        },
        "scout": {
            "alert_requests": len(scout_alerts),
            "verification_inferences": len(verifications),
            "verdicts": len(verdicts),
            "confirmed": sum(record.get("verdict") == "CONFIRMED" for record in verdicts),
            "rejected": sum(record.get("verdict") == "REJECTED" for record in verdicts),
            "raw_fire_max": summary(record["raw_fire_max"] for record in verifications),
            "inference_latency_ms": summary(
                record["inference_latency_ms"] for record in verifications
            ),
            "source_frame_age_at_start_ms": summary(
                record["frame_age_at_start_ms"] for record in verifications
            ),
            "queue_delay_ms": summary(record["queue_delay_ms"] for record in verifications),
            "logger_dropped_records_max": max(
                [int(record.get("logger_dropped_records", 0)) for record in verifications]
                or [0]
            ),
            "diagnostic_frames_recorded": sum(
                bool(record.get("diagnostic_frame_sha256")) for record in verifications
            ),
        },
    }

    event_groups = {
        "scout_alert_received": scout_alerts,
        "scout_verification": verifications,
        "scout_verdict": verdicts,
    }

    sentinel = None
    if arguments.sentinel_events:
        sentinel = read_jsonl(arguments.sentinel_events)
        alerts = events_of(sentinel, "hazard_alert_published")
        decisions = events_of(sentinel, "final_decision")
        inferences = events_of(sentinel, "inference")
        alert_to_decision = [
            (record["verdict_received_monotonic_ns"] - record["alert_sent_monotonic_ns"])
            / 1000000.0
            for record in decisions
        ]
        inference_latencies = [record["inference_latency_ms"] for record in inferences]
        latency_summary = summary(inference_latencies)
        result["raw_evidence"]["sentinel_events"] = {
            "path": os.path.abspath(arguments.sentinel_events),
            "sha256": sha256(arguments.sentinel_events),
            "records": len(sentinel),
        }
        result["sentinel"] = {
            "inference_frames": len(inferences),
            "inference_latency_ms": latency_summary,
            "derived_mean_inference_fps": (
                1000.0 / latency_summary["mean"] if latency_summary else None
            ),
            "hazard_alerts": len(alerts),
            "final_decisions": len(decisions),
            "confirmed": sum(record.get("decision") == "CONFIRMED" for record in decisions),
            "rejected": sum(record.get("decision") == "REJECTED" for record in decisions),
            "alert_to_final_decision_ms": summary(alert_to_decision),
            "alert_suppressed_records": len(events_of(sentinel, "alert_suppressed")),
            "local_tracking_observations": len(
                events_of(sentinel, "local_tracking_observation")
            ),
            "logger_dropped_records_max": max(
                [int(record.get("logger_dropped_records", 0)) for record in inferences]
                or [0]
            ),
        }
        event_groups["sentinel_alert"] = alerts
        event_groups["sentinel_final_decision"] = decisions

    result["event_correlation"] = identity_check(event_groups)

    if arguments.ground_truth:
        ground_truth = read_jsonl(arguments.ground_truth)
        starts = events_of(ground_truth, "HAZARD_VISIBLE_START")
        ends = events_of(ground_truth, "HAZARD_VISIBLE_END")
        if len(starts) != 1 or len(ends) != 1:
            raise ValueError("ground truth must contain exactly one visible start and end")
        start = utc(starts[0]["wall_time_utc"])
        end = utc(ends[0]["wall_time_utc"])
        if end <= start:
            raise ValueError("ground-truth visible end must be after start")
        in_interval = []
        before = []
        after = []
        for verdict in verdicts:
            observed = utc(verdict["wall_time_utc"])
            if observed < start:
                before.append(verdict)
            elif observed <= end:
                in_interval.append(verdict)
            else:
                after.append(verdict)
        result["raw_evidence"]["ground_truth"] = {
            "path": os.path.abspath(arguments.ground_truth),
            "sha256": sha256(arguments.ground_truth),
            "records": len(ground_truth),
        }
        result["ground_truth_interval"] = {
            "visible_start_utc": starts[0]["wall_time_utc"],
            "visible_end_utc": ends[0]["wall_time_utc"],
            "duration_seconds": (end - start).total_seconds(),
            "verdicts_before_visible_interval": len(before),
            "verdicts_in_visible_interval": len(in_interval),
            "confirmations_in_visible_interval": sum(
                record.get("verdict") == "CONFIRMED" for record in in_interval
            ),
            "rejections_in_visible_interval": sum(
                record.get("verdict") == "REJECTED" for record in in_interval
            ),
            "observed_confirmation_fraction": (
                sum(record.get("verdict") == "CONFIRMED" for record in in_interval)
                / float(len(in_interval))
                if in_interval
                else None
            ),
            "verdicts_after_visible_interval": len(after),
            "classification_clock": "wall_time_utc",
            "clock_resolution_limitation": (
                "Node event wall times are logged to whole seconds whereas ground truth uses "
                "milliseconds; boundary-adjacent events require manual review."
            ),
        }

    result["claim_boundary"] = {
        "permitted": (
            "Descriptive proof-of-function and timing claims for this stationary, "
            "condition-specific laboratory trial."
        ),
        "not_permitted": [
            "population-level recall, precision, false-positive rate, or false-negative rate",
            "flight or localization performance",
            "smoke-detection performance",
            "industrial-environment generalization",
        ],
    }
    parent = os.path.dirname(os.path.abspath(arguments.output))
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(arguments.output, "w", encoding="utf-8") as output:
        json.dump(result, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps({"status": "PASS", "output": os.path.abspath(arguments.output)}))


if __name__ == "__main__":
    main()
