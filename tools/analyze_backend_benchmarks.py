#!/usr/bin/env python3
"""Verify benchmark evidence and export sample-level and comparative results."""

from __future__ import print_function

import argparse
import csv
import hashlib
import json
import os
from datetime import datetime, timezone


METRICS = ("preprocess_ms", "inference_ms", "decode_ms", "pipeline_ms")


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def parse_benchmark_envelope(path, expected_label="camera_free_backend_benchmark"):
    with open(path, "r", encoding="utf-8") as source:
        envelope = json.load(source)
    record = envelope["record"]
    calculated = sha256_bytes(canonical_json(record))
    if calculated != envelope["record_sha256"]:
        raise ValueError("record hash mismatch: {}".format(path))
    if record.get("label") != expected_label:
        return None
    if record.get("exit_code") != 0:
        raise ValueError("benchmark command failed: {}".format(path))
    lines = [line.strip() for line in record.get("stdout", "").splitlines() if line.strip()]
    json_lines = [line for line in lines if line.startswith("{")]
    if not json_lines:
        raise ValueError("benchmark stdout is empty: {}".format(path))
    benchmark = json.loads(json_lines[-1])
    if benchmark.get("status") != "PASS":
        raise ValueError("benchmark result did not pass: {}".format(path))
    return {
        "filename": os.path.basename(path),
        "file_sha256": sha256_file(path),
        "record_sha256": envelope["record_sha256"],
        "device": record["device"],
        "benchmark": benchmark,
    }


def derive_device_metrics(benchmark):
    means = {metric: benchmark["summaries_ms"][metric]["mean"] for metric in METRICS}
    pipeline_mean = means["pipeline_ms"]
    return {
        "mean_pipeline_fps": 1000.0 / pipeline_mean,
        "mean_component_share_percent": {
            metric.replace("_ms", ""): means[metric] * 100.0 / pipeline_mean
            for metric in ("preprocess_ms", "inference_ms", "decode_ms")
        },
    }


def compare_devices(sentinel_pipeline_mean_ms, scout_pipeline_mean_ms):
    sentinel_pipeline_mean_ms = float(sentinel_pipeline_mean_ms)
    scout_pipeline_mean_ms = float(scout_pipeline_mean_ms)
    if min(sentinel_pipeline_mean_ms, scout_pipeline_mean_ms) <= 0.0:
        raise ValueError("pipeline means must be positive")
    return {
        "scout_to_sentinel_mean_pipeline_latency_ratio": (
            scout_pipeline_mean_ms / sentinel_pipeline_mean_ms
        ),
        "sentinel_mean_pipeline_latency_reduction_relative_to_scout_percent": (
            (scout_pipeline_mean_ms - sentinel_pipeline_mean_ms)
            * 100.0
            / scout_pipeline_mean_ms
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_directory")
    parser.add_argument("--output-directory", required=True)
    parser.add_argument(
        "--label", default="camera_free_backend_benchmark", help="evidence label"
    )
    arguments = parser.parse_args()
    evidence_directory = os.path.abspath(arguments.evidence_directory)
    output_directory = os.path.abspath(arguments.output_directory)

    records = []
    for filename in sorted(os.listdir(evidence_directory)):
        if not filename.endswith(".json"):
            continue
        parsed = parse_benchmark_envelope(
            os.path.join(evidence_directory, filename), arguments.label
        )
        if parsed is not None:
            records.append(parsed)
    if len(records) != 2 or {record["device"] for record in records} != {
        "sentinel",
        "scout",
    }:
        raise ValueError("exactly one Sentinel and one Scout benchmark are required")
    by_device = {record["device"]: record for record in records}

    if not os.path.isdir(output_directory):
        os.makedirs(output_directory)
    csv_path = os.path.join(output_directory, "benchmark_samples.csv")
    with open(csv_path, "x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=(
                "device",
                "backend",
                "model_sha256",
                "iteration_index",
                "preprocess_ms",
                "inference_ms",
                "decode_ms",
                "pipeline_ms",
                "decoded_fire_detections",
            ),
        )
        writer.writeheader()
        for device in ("sentinel", "scout"):
            benchmark = by_device[device]["benchmark"]
            for sample in benchmark["samples"]:
                writer.writerow(
                    {
                        "device": device,
                        "backend": benchmark["backend"],
                        "model_sha256": benchmark["model_sha256"],
                        "iteration_index": sample["iteration_index"],
                        "preprocess_ms": sample["preprocess_ms"],
                        "inference_ms": sample["inference_ms"],
                        "decode_ms": sample["decode_ms"],
                        "pipeline_ms": sample["pipeline_ms"],
                        "decoded_fire_detections": sample[
                            "decoded_fire_detections"
                        ],
                    }
                )

    device_results = {}
    for device in ("sentinel", "scout"):
        source = by_device[device]
        benchmark = source["benchmark"]
        device_results[device] = {
            "source_evidence_filename": source["filename"],
            "source_evidence_file_sha256": source["file_sha256"],
            "source_record_sha256": source["record_sha256"],
            "backend": benchmark["backend"],
            "model_sha256": benchmark["model_sha256"],
            "model_path": benchmark["model_path"],
            "python_version": benchmark["python_version"],
            "platform": benchmark["platform"],
            "warmup_count": benchmark["warmup_count"],
            "iteration_count": benchmark["iteration_count"],
            "backend_load_ms": benchmark["backend_load_ms"],
            "summaries_ms": benchmark["summaries_ms"],
            "derived": derive_device_metrics(benchmark),
            "resource_before_backend_load": benchmark[
                "resource_before_backend_load"
            ],
            "resource_after_backend_load": benchmark[
                "resource_after_backend_load"
            ],
            "resource_after_benchmark": benchmark["resource_after_benchmark"],
        }

    sentinel_mean = device_results["sentinel"]["summaries_ms"]["pipeline_ms"][
        "mean"
    ]
    scout_mean = device_results["scout"]["summaries_ms"]["pipeline_ms"]["mean"]
    warmup_counts = {
        result["warmup_count"] for result in device_results.values()
    }
    iteration_counts = {
        result["iteration_count"] for result in device_results.values()
    }
    if len(warmup_counts) != 1 or len(iteration_counts) != 1:
        raise ValueError("Sentinel and Scout benchmark counts must match")
    analysis = {
        "schema_version": 1,
        "generated_utc": utc_now(),
        "source_evidence_directory": evidence_directory,
        "source_evidence_label": arguments.label,
        "sample_csv": os.path.basename(csv_path),
        "sample_csv_sha256": sha256_file(csv_path),
        "protocol": {
            "frame": "fixed black BGR uint8 image",
            "frame_shape": [480, 640, 3],
            "resize_mode": "letterbox",
            "warmups_excluded_from_statistics": next(iter(warmup_counts)),
            "measured_iterations_per_device": next(iter(iteration_counts)),
            "units": "milliseconds unless explicitly stated",
            "variance_definition": "population variance with divisor n",
            "percentile_definition": (
                "linear interpolation at (n - 1) * percentage / 100"
            ),
        },
        "device_results": device_results,
        "comparison": compare_devices(sentinel_mean, scout_mean),
        "inferential_statistics": {
            "confidence_intervals_reported": False,
            "reason": (
                "The 50 serial iterations came from one run per device and a "
                "repeated deterministic frame; independence is not established."
            ),
        },
        "claim_boundary": {
            "permitted": (
                "descriptive camera-free runtime comparison for these exact "
                "hardware, model, runtime, and configuration combinations"
            ),
            "not_permitted": [
                "model accuracy or detection-rate comparison",
                "model-only superiority claim",
                "camera or ROS 2 end-to-end latency claim",
                "power-consumption claim",
                "industrial-environment generalization",
            ],
            "heterogeneity_warning": (
                "The devices, models, runtimes, output channel counts, and "
                "implementation stacks differ, so this is a system-role "
                "comparison rather than a controlled model-only comparison."
            ),
        },
    }
    summary_path = os.path.join(output_directory, "benchmark_analysis.json")
    with open(summary_path, "x", encoding="utf-8") as output:
        json.dump(analysis, output, indent=2, sort_keys=True)
        output.write("\n")
    print("SAMPLE_CSV={}".format(csv_path))
    print("SAMPLE_CSV_SHA256={}".format(sha256_file(csv_path)))
    print("ANALYSIS_JSON={}".format(summary_path))
    print("ANALYSIS_JSON_SHA256={}".format(sha256_file(summary_path)))


if __name__ == "__main__":
    main()
