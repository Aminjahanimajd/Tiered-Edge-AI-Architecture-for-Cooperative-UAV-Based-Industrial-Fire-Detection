#!/usr/bin/env python3
"""Verify and analyze correlated ROS 2 roundtrip evidence records."""

from __future__ import print_function

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
from datetime import datetime, timezone


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values, percentage):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile requires values")
    position = (len(ordered) - 1) * float(percentage) / 100.0
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def timing_summary(values):
    values = [float(value) for value in values]
    if not values:
        raise ValueError("timing summary requires values")
    q1 = percentile(values, 25)
    q3 = percentile(values, 75)
    upper_fence = q3 + 1.5 * (q3 - q1)
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
        "population_standard_deviation": statistics.pstdev(values),
        "p05": percentile(values, 5),
        "p25": q1,
        "p75": q3,
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "tukey_upper_fence": upper_fence,
        "count_above_10_ms": sum(value > 10.0 for value in values),
        "count_above_20_ms": sum(value > 20.0 for value in values),
        "count_above_50_ms": sum(value > 50.0 for value in values),
        "count_above_100_ms": sum(value > 100.0 for value in values),
    }


def parse_result(envelope_path):
    with open(envelope_path, "r", encoding="utf-8") as source:
        envelope = json.load(source)
    record = envelope["record"]
    calculated = hashlib.sha256(canonical_json(record)).hexdigest()
    if calculated != envelope["record_sha256"]:
        raise ValueError("record hash mismatch: {}".format(envelope_path))
    if not record.get("label", "").startswith("correlated_ros2_roundtrip_100"):
        return None
    if record.get("exit_code") != 0:
        raise ValueError("roundtrip command failed: {}".format(envelope_path))
    lines = [line.strip() for line in record.get("stdout", "").splitlines()]
    json_lines = [line for line in lines if line.startswith("{")]
    if not json_lines:
        raise ValueError("roundtrip result JSON missing: {}".format(envelope_path))
    result = json.loads(json_lines[-1])
    return {
        "filename": os.path.basename(envelope_path),
        "file_sha256": sha256_file(envelope_path),
        "record_sha256": envelope["record_sha256"],
        "device": record["device"],
        "result": result,
    }


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_directory")
    parser.add_argument("--output-directory", required=True)
    arguments = parser.parse_args()
    evidence_directory = os.path.abspath(arguments.evidence_directory)
    output_directory = os.path.abspath(arguments.output_directory)
    records = []
    for filename in sorted(os.listdir(evidence_directory)):
        if filename.endswith(".json"):
            parsed = parse_result(os.path.join(evidence_directory, filename))
            if parsed is not None:
                records.append(parsed)
    initiators = [record for record in records if record["result"]["role"] == "initiator"]
    responders = [record for record in records if record["result"]["role"] == "responder"]
    if len(initiators) != 3 or len(responders) != 3:
        raise ValueError("three initiator and three responder records are required")

    responder_by_trial = {record["result"]["trial_id"]: record for record in responders}
    rows = []
    trials = {}
    source_records = []
    for record in records:
        source_records.append(
            {
                "filename": record["filename"],
                "file_sha256": record["file_sha256"],
                "record_sha256": record["record_sha256"],
                "device": record["device"],
                "role": record["result"]["role"],
                "trial_id": record["result"]["trial_id"],
            }
        )
    for initiator in sorted(initiators, key=lambda item: item["result"]["trial_id"]):
        result = initiator["result"]
        trial_id = result["trial_id"]
        responder = responder_by_trial.get(trial_id)
        if responder is None:
            raise ValueError("responder missing for {}".format(trial_id))
        rtts = []
        for sample in result["samples"]:
            row = {
                "trial_id": trial_id,
                "sequence": sample["sequence"],
                "event_id": sample["event_id"],
                "received": sample["received"],
                "correlation_match": sample.get("correlation_match"),
                "round_trip_ms": sample.get("round_trip_ms"),
            }
            rows.append(row)
            if sample["received"]:
                rtts.append(sample["round_trip_ms"])
        trials[trial_id] = {
            "requested_count": result["requested_count"],
            "attempted_count": result["attempted_count"],
            "received_count": result["received_count"],
            "missing_count": result["missing_count"],
            "mismatched_event_ids": result["mismatched_event_ids"],
            "unexpected_event_ids": result["unexpected_event_ids"],
            "responder_received_count": responder["result"]["received_count"],
            "responder_duplicate_event_ids": responder["result"][
                "duplicate_event_ids"
            ],
            "rtt_summary_ms": timing_summary(rtts),
        }

    if not os.path.isdir(output_directory):
        os.makedirs(output_directory)
    csv_path = os.path.join(output_directory, "ros_roundtrip_samples.csv")
    with open(csv_path, "x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=(
                "trial_id",
                "sequence",
                "event_id",
                "received",
                "correlation_match",
                "round_trip_ms",
            ),
        )
        writer.writeheader()
        writer.writerows(rows)

    pooled_rtts = [row["round_trip_ms"] for row in rows if row["received"]]
    pooled_summary = timing_summary(pooled_rtts)
    upper_fence = pooled_summary["tukey_upper_fence"]
    tail_events = sorted(
        [
            {
                "trial_id": row["trial_id"],
                "sequence": row["sequence"],
                "event_id": row["event_id"],
                "round_trip_ms": row["round_trip_ms"],
            }
            for row in rows
            if row["received"] and row["round_trip_ms"] > upper_fence
        ],
        key=lambda row: row["round_trip_ms"],
        reverse=True,
    )
    total_attempted = sum(trial["attempted_count"] for trial in trials.values())
    total_received = sum(trial["received_count"] for trial in trials.values())
    analysis = {
        "schema_version": 1,
        "generated_utc": utc_now(),
        "source_evidence_directory": evidence_directory,
        "source_records": source_records,
        "sample_csv": os.path.basename(csv_path),
        "sample_csv_sha256": sha256_file(csv_path),
        "protocol": {
            "trial_count": 3,
            "requested_roundtrips_per_trial": 100,
            "initiator": "Sentinel",
            "responder": "Scout",
            "request_topic": "/swarm/hazard_alert",
            "reply_topic": "/swarm/hazard_verdict",
            "qos": "RELIABLE, VOLATILE, depth 100",
            "rmw": "rmw_cyclonedds_cpp",
            "network_interface": "wlan0",
            "measurement_clock": "Sentinel monotonic clock",
        },
        "trials": trials,
        "pooled": {
            "attempted_count": total_attempted,
            "received_count": total_received,
            "missing_count": total_attempted - total_received,
            "observed_reply_fraction": (
                float(total_received) / total_attempted if total_attempted else 0.0
            ),
            "mismatch_count": sum(
                len(trial["mismatched_event_ids"]) for trial in trials.values()
            ),
            "responder_duplicate_count": sum(
                len(trial["responder_duplicate_event_ids"])
                for trial in trials.values()
            ),
            "rtt_summary_ms": pooled_summary,
            "tukey_tail_events": tail_events,
        },
        "claim_boundary": {
            "permitted": (
                "observed correlated application-level request/reply delivery and "
                "round-trip timing in these three camera-free sessions"
            ),
            "not_permitted": [
                "one-way latency",
                "DDS packet-loss rate",
                "general reliability guarantee",
                "camera-to-decision latency",
                "loaded or industrial-network performance",
            ],
            "note": (
                "Reliable DDS may retransmit below the application layer; a received "
                "reply does not prove that no network packet was lost."
            ),
        },
        "inferential_statistics": {
            "reported": False,
            "reason": (
                "Serial observations within three consecutive sessions are not "
                "established as independent or representative of other conditions."
            ),
        },
    }
    analysis_path = os.path.join(output_directory, "ros_roundtrip_analysis.json")
    with open(analysis_path, "x", encoding="utf-8") as output:
        json.dump(analysis, output, indent=2, sort_keys=True)
        output.write("\n")
    print("SAMPLE_CSV={}".format(csv_path))
    print("SAMPLE_CSV_SHA256={}".format(sha256_file(csv_path)))
    print("ANALYSIS_JSON={}".format(analysis_path))
    print("ANALYSIS_JSON_SHA256={}".format(sha256_file(analysis_path)))


if __name__ == "__main__":
    main()
