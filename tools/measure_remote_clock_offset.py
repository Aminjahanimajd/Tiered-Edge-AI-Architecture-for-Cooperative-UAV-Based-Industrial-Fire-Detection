#!/usr/bin/env python3
"""Estimate remote UTC offset over one persistent, key-authenticated SSH stream."""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone


REMOTE_COMMAND = "while IFS= read -r line; do date +%s%N; done"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def wall_time_ns():
    function = getattr(time, "time_ns", None)
    if function is not None:
        return function()
    return int(time.time() * 1000000000)


def monotonic_ns():
    function = getattr(time, "monotonic_ns", None)
    if function is not None:
        return function()
    return int(time.monotonic() * 1000000000)


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def summarize_samples(samples):
    if not samples:
        raise ValueError("at least one clock sample is required")
    best = min(samples, key=lambda sample: sample["round_trip_monotonic_ns"])
    offsets = [sample["remote_minus_local_midpoint_ns"] for sample in samples]
    round_trips = [sample["round_trip_monotonic_ns"] for sample in samples]
    return {
        "sample_count": len(samples),
        "best_sample_index": best["sample_index"],
        "best_remote_minus_local_midpoint_ns": best[
            "remote_minus_local_midpoint_ns"
        ],
        "best_uncertainty_plus_or_minus_ns": best["uncertainty_plus_or_minus_ns"],
        "minimum_round_trip_ns": min(round_trips),
        "median_round_trip_ns": statistics.median(round_trips),
        "maximum_round_trip_ns": max(round_trips),
        "median_remote_minus_local_midpoint_ns": statistics.median(offsets),
        "minimum_remote_minus_local_midpoint_ns": min(offsets),
        "maximum_remote_minus_local_midpoint_ns": max(offsets),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--known-hosts", required=True)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--output-directory", required=True)
    arguments = parser.parse_args()
    if arguments.samples <= 0:
        parser.error("--samples must be positive")

    output_directory = os.path.abspath(arguments.output_directory)
    os.makedirs(output_directory, exist_ok=True)
    record_id = uuid.uuid4().hex
    started_utc = utc_now()
    ssh_arguments = [
        "ssh",
        "-i",
        os.path.abspath(arguments.key),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "UserKnownHostsFile={}".format(os.path.abspath(arguments.known_hosts)),
        "{}@{}".format(arguments.user, arguments.host),
        REMOTE_COMMAND,
    ]
    samples = []
    stderr = ""
    exit_code = 1
    error = None
    process = None
    try:
        process = subprocess.Popen(
            ssh_arguments,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1,
        )
        # Establish the SSH stream before measured samples.
        process.stdin.write("warmup\n")
        process.stdin.flush()
        warmup_response = process.stdout.readline().strip()
        int(warmup_response)

        for index in range(arguments.samples):
            local_before_wall_ns = wall_time_ns()
            local_before_monotonic_ns = monotonic_ns()
            process.stdin.write("sample-{}\n".format(index))
            process.stdin.flush()
            response = process.stdout.readline().strip()
            local_after_monotonic_ns = monotonic_ns()
            local_after_wall_ns = wall_time_ns()
            remote_wall_ns = int(response)
            round_trip_ns = local_after_monotonic_ns - local_before_monotonic_ns
            midpoint_ns = (local_before_wall_ns + local_after_wall_ns) // 2
            samples.append(
                {
                    "sample_index": index,
                    "local_before_wall_ns": local_before_wall_ns,
                    "local_after_wall_ns": local_after_wall_ns,
                    "local_before_monotonic_ns": local_before_monotonic_ns,
                    "local_after_monotonic_ns": local_after_monotonic_ns,
                    "remote_wall_ns": remote_wall_ns,
                    "local_wall_midpoint_ns": midpoint_ns,
                    "round_trip_monotonic_ns": round_trip_ns,
                    "remote_minus_local_midpoint_ns": remote_wall_ns - midpoint_ns,
                    "uncertainty_plus_or_minus_ns": round_trip_ns // 2,
                }
            )
        process.stdin.close()
        stderr = process.stderr.read()
        exit_code = process.wait(timeout=10)
        if exit_code != 0:
            error = "persistent SSH clock stream exited nonzero"
    except Exception as exc:
        error = "{}: {}".format(type(exc).__name__, exc)
        if process is not None:
            try:
                process.kill()
            except Exception:
                pass
            try:
                stderr += process.stderr.read()
            except Exception:
                pass
            try:
                exit_code = process.wait(timeout=5)
            except Exception:
                exit_code = 1

    record = {
        "schema_version": 1,
        "record_id": record_id,
        "label": "persistent_ssh_clock_offset_probe",
        "device": arguments.device,
        "target": "{}@{}".format(arguments.user, arguments.host),
        "authentication": "dedicated_key_batch_mode",
        "host_key_checking": "strict_dedicated_known_hosts",
        "remote_command": REMOTE_COMMAND,
        "started_utc": started_utc,
        "finished_utc": utc_now(),
        "clock_offset_definition": "remote_utc_ns - local_utc_midpoint_ns",
        "uncertainty_definition": "plus_or_minus_one_half_observed_round_trip_ns",
        "asymmetric_path_bias_possible": True,
        "clock_was_modified": False,
        "warmup_excluded": True,
        "samples": samples,
        "summary": summarize_samples(samples) if samples else None,
        "stderr": stderr,
        "exit_code": exit_code,
        "error": error,
        "latency_claim_permitted": False,
    }
    record_hash = hashlib.sha256(canonical_json(record)).hexdigest()
    envelope = {"record": record, "record_sha256": record_hash}
    filename = "{}_{}_clock_offset_{}.json".format(
        started_utc.replace(":", "").replace("-", ""),
        arguments.device,
        record_id[:8],
    )
    output_path = os.path.join(output_directory, filename)
    with open(output_path, "x", encoding="utf-8") as output:
        json.dump(envelope, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    print(json.dumps(record["summary"], sort_keys=True))
    print("EVIDENCE_PATH={}".format(output_path))
    print("EVIDENCE_RECORD_SHA256={}".format(record_hash))
    if exit_code != 0 or error is not None:
        if error:
            print(error, file=sys.stderr)
        raise SystemExit(exit_code if exit_code != 0 else 1)


if __name__ == "__main__":
    main()
