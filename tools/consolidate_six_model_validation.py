#!/usr/bin/env python3
"""Consolidate the frozen six-model validation evidence without opening test data."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path


CANONICAL_RUNS = {
    "yolov8n_416": "yolov8n_416_timing_retry2",
    "yolov8n_640": "yolov8n_640",
    "yolov8s_416": "yolov8s_416",
    "yolov8s_640": "yolov8s_640",
    "ssd_mobilenet_v2_fpnlite_320": "ssd_mobilenet_v2_fpnlite_320_retry2_dynamic_signature",
    "efficientdet_lite0_320": "efficientdet_lite0_320",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def nested(source: dict, *keys):
    value = source
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def is_dominated(candidate: dict, rows: list[dict]) -> bool:
    """Maximize AP50-95 and minimize observed mean inference latency."""
    for other in rows:
        if other is candidate:
            continue
        at_least_as_accurate = other["ap50_95"] >= candidate["ap50_95"]
        at_least_as_fast = other["latency_mean_ms"] <= candidate["latency_mean_ms"]
        strictly_better = (
            other["ap50_95"] > candidate["ap50_95"]
            or other["latency_mean_ms"] < candidate["latency_mean_ms"]
        )
        if at_least_as_accurate and at_least_as_fast and strictly_better:
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparison-directory", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()

    comparison = args.comparison_directory.resolve()
    contract_path = args.contract.resolve()
    output = args.output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    contract = load_json(contract_path)
    if not contract.get("test_split_locked"):
        raise ValueError("validation consolidation requires the test split to remain locked")

    config_by_id = {item["model_id"]: item for item in contract["models"]}
    rows: list[dict] = []
    evidence_files: list[dict] = []
    for model_id, evidence_id in CANONICAL_RUNS.items():
        run_dir = comparison / "runs" / evidence_id
        resource_dir = comparison / "resources" / evidence_id
        required = {
            "run": run_dir / "run_summary.json",
            "metrics": run_dir / "metrics.json",
            "latency": run_dir / "latency_summary.json",
            "bootstrap": run_dir / "grouped_bootstrap.json",
            "sanitization": run_dir / "prediction_sanitization.json",
            "predictions": run_dir / "predictions_evaluable.json",
            "resources": resource_dir / "run_summary.json",
            "resource_samples": resource_dir / "resource_samples.csv",
        }
        missing = [str(path) for path in required.values() if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"{model_id} is incomplete; missing {missing}")
        run = load_json(required["run"])
        metrics = load_json(required["metrics"])
        latency = load_json(required["latency"])
        bootstrap = load_json(required["bootstrap"])
        sanitization = load_json(required["sanitization"])
        resources = load_json(required["resources"])
        if run.get("status") != "completed" or resources.get("status") != "completed":
            raise ValueError(f"{model_id} does not have completed run/resource status")
        if nested(run, "parameters", "image_count") != contract["validation"]["expected_images"]:
            raise ValueError(f"{model_id} image count differs from frozen contract")
        thresholded = metrics["thresholded_iou50"]
        size_recall = thresholded["ground_truth_recall_by_relative_box_area"]
        row = {
            "model_id": model_id,
            "canonical_evidence_id": evidence_id,
            "framework": run["framework"],
            "runtime_device": "CPU/XNNPACK" if model_id == "efficientdet_lite0_320" else "GPU",
            "input_size": config_by_id[model_id]["input_size"],
            "image_count": metrics["image_count"],
            "ground_truth_box_count": metrics["ground_truth_box_count"],
            "prediction_count_at_floor": metrics["prediction_count_at_floor"],
            "parameter_count": run.get("parameter_count"),
            "trainable_parameter_count": run.get("trainable_parameter_count"),
            "tf_function_tracing_count": run.get("tf_function_tracing_count"),
            "ap50_95": metrics["coco"]["ap_50_95"],
            "ap50": metrics["coco"]["ap_50"],
            "ap75": metrics["coco"]["ap_75"],
            "threshold": thresholded["threshold"],
            "tp": thresholded["tp"],
            "fp": thresholded["fp"],
            "fn": thresholded["fn"],
            "precision": thresholded["precision"],
            "recall": thresholded["recall"],
            "f1": thresholded["f1"],
            "background_false_positive_image_rate": thresholded[
                "background_false_positive_image_rate"
            ],
            "very_small_lt_1pct_recall": size_recall["very_small_lt_1pct"]["recall"],
            "small_1_to_lt_5pct_recall": size_recall["small_1_to_lt_5pct"]["recall"],
            "latency_mean_ms": latency["mean"],
            "latency_median_ms": latency["median"],
            "latency_p95_ms": latency["p95"],
            "latency_std_ms": latency["standard_deviation_sample"],
            "throughput_from_mean_fps": latency["throughput_from_mean_fps"],
            "resource_duration_seconds": resources["duration_seconds"],
            "resource_sample_count": resources["sample_count"],
            "system_ram_mean_mib": nested(resources, "metrics", "system_ram_used_mib", "mean"),
            "system_ram_max_mib": nested(resources, "metrics", "system_ram_used_mib", "maximum"),
            "gpu_utilization_mean_percent": nested(
                resources, "metrics", "gpu_utilization_percent", "mean"
            ),
            "gpu_memory_max_mib": nested(resources, "metrics", "gpu_memory_used_mib", "maximum"),
            "predictions_sha256": metrics["predictions_sha256"],
            "latency_csv_sha256": latency["latency_csv_sha256"],
            "bootstrap_sha256": sha256(required["bootstrap"]),
            "excluded_prediction_count": sanitization["excluded_count"],
            "precision_ci95_lower": nested(bootstrap, "intervals", "precision", "lower_95_percentile"),
            "precision_ci95_upper": nested(bootstrap, "intervals", "precision", "upper_95_percentile"),
            "recall_ci95_lower": nested(bootstrap, "intervals", "recall", "lower_95_percentile"),
            "recall_ci95_upper": nested(bootstrap, "intervals", "recall", "upper_95_percentile"),
            "f1_ci95_lower": nested(bootstrap, "intervals", "f1", "lower_95_percentile"),
            "f1_ci95_upper": nested(bootstrap, "intervals", "f1", "upper_95_percentile"),
        }
        rows.append(row)
        for role, path in required.items():
            evidence_files.append(
                {
                    "model_id": model_id,
                    "role": role,
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )

    for row in rows:
        row["exploratory_ap_latency_pareto"] = not is_dominated(row, rows)

    output.mkdir(parents=True)
    csv_path = output / "validation_model_comparison.csv"
    with csv_path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    result = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "status": "completed",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "protocol_id": contract["protocol_id"],
        "contract_sha256": sha256(contract_path),
        "test_split_locked": True,
        "canonical_runs": CANONICAL_RUNS,
        "candidate_count": len(rows),
        "rows": rows,
        "exploratory_pareto_definition": {
            "maximize": "validation AP50-95",
            "minimize": "observed mean single-image pipeline inference latency",
            "limitation": (
                "Runtime/framework/device paths differ; the front describes observed pipelines "
                "on this laptop and is not an architecture-only latency ranking."
            ),
        },
        "evidence_files": evidence_files,
    }
    json_path = output / "validation_model_comparison.json"
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "files": [
            {"path": str(csv_path), "bytes": csv_path.stat().st_size, "sha256": sha256(csv_path)},
            {"path": str(json_path), "bytes": json_path.stat().st_size, "sha256": sha256(json_path)},
        ],
    }
    (output / "consolidation_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "completed", "rows": len(rows), "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
