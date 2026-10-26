#!/usr/bin/env python3
"""Compare baseline and optimized camera-free backend analysis records."""

from __future__ import print_function

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone


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


def relative_reduction_percent(before, after):
    before = float(before)
    after = float(after)
    if before <= 0.0 or after < 0.0:
        raise ValueError("before must be positive and after cannot be negative")
    return (before - after) * 100.0 / before


def compare_device(before, after):
    if before["model_sha256"] != after["model_sha256"]:
        raise ValueError("model hashes differ between baseline and optimized runs")
    result = {
        "model_sha256": before["model_sha256"],
        "metrics": {},
    }
    for metric in ("preprocess_ms", "inference_ms", "decode_ms", "pipeline_ms"):
        before_mean = before["summaries_ms"][metric]["mean"]
        after_mean = after["summaries_ms"][metric]["mean"]
        result["metrics"][metric] = {
            "baseline_mean_ms": before_mean,
            "optimized_mean_ms": after_mean,
            "absolute_change_ms": after_mean - before_mean,
            "relative_reduction_percent": relative_reduction_percent(
                before_mean, after_mean
            ),
        }
    before_fps = before["derived"]["mean_pipeline_fps"]
    after_fps = after["derived"]["mean_pipeline_fps"]
    result["pipeline_rate"] = {
        "baseline_mean_pipelines_per_second": before_fps,
        "optimized_mean_pipelines_per_second": after_fps,
        "rate_ratio_optimized_to_baseline": after_fps / before_fps,
        "relative_increase_percent": (after_fps - before_fps) * 100.0 / before_fps,
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline_analysis")
    parser.add_argument("optimized_analysis")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    baseline_path = os.path.abspath(arguments.baseline_analysis)
    optimized_path = os.path.abspath(arguments.optimized_analysis)
    output_path = os.path.abspath(arguments.output)
    with open(baseline_path, "r", encoding="utf-8") as source:
        baseline = json.load(source)
    with open(optimized_path, "r", encoding="utf-8") as source:
        optimized = json.load(source)

    comparison = {
        "schema_version": 1,
        "generated_utc": utc_now(),
        "baseline_analysis_path": baseline_path,
        "baseline_analysis_sha256": sha256_file(baseline_path),
        "optimized_analysis_path": optimized_path,
        "optimized_analysis_sha256": sha256_file(optimized_path),
        "comparison_design": {
            "type": "separate serial before-and-after runs",
            "paired_samples": False,
            "inferential_statistics_reported": False,
            "controlled_fields": [
                "device",
                "deployed model hash",
                "synthetic input",
                "resize mode",
                "warm-up count",
                "measured iteration count",
                "confidence threshold",
                "NMS threshold",
            ],
            "changed_field": "candidate filtering and coordinate decoding implementation",
            "remaining_confounders": [
                "ordinary operating-system background load",
                "temperature at run start",
                "uncontrolled run-to-run variation",
            ],
        },
        "devices": {},
        "claim_boundary": (
            "Descriptive software-optimization effect for the two exact deployed "
            "systems and fixed synthetic protocol; no accuracy, energy, camera, "
            "ROS 2, or statistical-significance claim."
        ),
    }
    for device in ("sentinel", "scout"):
        comparison["devices"][device] = compare_device(
            baseline["device_results"][device],
            optimized["device_results"][device],
        )
    parent = os.path.dirname(output_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(output_path, "x", encoding="utf-8") as output:
        json.dump(comparison, output, indent=2, sort_keys=True)
        output.write("\n")
    print("COMPARISON_JSON={}".format(output_path))
    print("COMPARISON_JSON_SHA256={}".format(sha256_file(output_path)))


if __name__ == "__main__":
    main()
