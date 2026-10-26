#!/usr/bin/env python3
"""Consolidate the one-time frozen-threshold six-model test evidence."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path


MODEL_IDS = (
    "yolov8n_416",
    "yolov8n_640",
    "yolov8s_416",
    "yolov8s_640",
    "ssd_mobilenet_v2_fpnlite_320",
    "efficientdet_lite0_320",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def nested(source: dict, *keys):
    value = source
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-directory", type=Path, required=True)
    parser.add_argument("--validation-comparison", type=Path, required=True)
    parser.add_argument("--selection-freeze", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()

    test_directory = args.test_directory.resolve()
    validation_path = args.validation_comparison.resolve()
    freeze_path = args.selection_freeze.resolve()
    output = args.output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    validation = load(validation_path)
    freeze = load(freeze_path)
    validation_by_id = {row["model_id"]: row for row in validation["rows"]}
    thresholds = freeze["validation_thresholds_iou50"]

    rows = []
    evidence_files = []
    evaluator_hashes = set()
    for model_id in MODEL_IDS:
        run_dir = test_directory / "runs" / model_id
        required = {
            "run": run_dir / "run_summary.json",
            "metrics": run_dir / "metrics.json",
            "latency": run_dir / "latency_summary.json",
            "bootstrap": run_dir / "grouped_bootstrap.json",
            "sanitization": run_dir / "prediction_sanitization.json",
            "predictions": run_dir / "predictions_evaluable.json",
        }
        missing = [str(path) for path in required.values() if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"{model_id} incomplete: {missing}")
        run = load(required["run"])
        metrics = load(required["metrics"])
        latency = load(required["latency"])
        bootstrap = load(required["bootstrap"])
        sanitization = load(required["sanitization"])
        thresholded = metrics["thresholded_iou50"]
        if run.get("status") != "completed" or metrics.get("split") != "test":
            raise ValueError(f"{model_id} test bundle status/split is invalid")
        if metrics["image_count"] != 733 or run["parameters"]["image_count"] != 733:
            raise ValueError(f"{model_id} does not contain 733 test observations")
        if abs(float(thresholded["threshold"]) - float(thresholds[model_id])) > 1e-12:
            raise ValueError(f"{model_id} test threshold differs from selection freeze")
        evaluator_hashes.add(metrics["evaluator_sha256"])
        validation_row = validation_by_id[model_id]
        size_recall = thresholded["ground_truth_recall_by_relative_box_area"]
        row = {
            "model_id": model_id,
            "framework": run["framework"],
            "runtime_device": "CPU/XNNPACK" if model_id == "efficientdet_lite0_320" else "GPU",
            "image_count": metrics["image_count"],
            "ground_truth_box_count": metrics["ground_truth_box_count"],
            "threshold_frozen_from_validation": thresholded["threshold"],
            "ap50_95": metrics["coco"]["ap_50_95"],
            "ap50": metrics["coco"]["ap_50"],
            "ap75": metrics["coco"]["ap_75"],
            "ap_small": metrics["coco"]["ap_small"],
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
            "throughput_from_mean_fps": latency["throughput_from_mean_fps"],
            "validation_ap50_95": validation_row["ap50_95"],
            "validation_f1": validation_row["f1"],
            "ap50_95_test_minus_validation": metrics["coco"]["ap_50_95"] - validation_row["ap50_95"],
            "f1_test_minus_validation": thresholded["f1"] - validation_row["f1"],
            "precision_ci95_lower": nested(bootstrap, "intervals", "precision", "lower_95_percentile"),
            "precision_ci95_upper": nested(bootstrap, "intervals", "precision", "upper_95_percentile"),
            "recall_ci95_lower": nested(bootstrap, "intervals", "recall", "lower_95_percentile"),
            "recall_ci95_upper": nested(bootstrap, "intervals", "recall", "upper_95_percentile"),
            "f1_ci95_lower": nested(bootstrap, "intervals", "f1", "lower_95_percentile"),
            "f1_ci95_upper": nested(bootstrap, "intervals", "f1", "upper_95_percentile"),
            "predictions_sha256": metrics["predictions_sha256"],
            "latency_csv_sha256": latency["latency_csv_sha256"],
            "excluded_prediction_count": sanitization["excluded_count"],
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

    if len(evaluator_hashes) != 1 or next(iter(evaluator_hashes)) != freeze["evaluator_sha256"]:
        raise ValueError("test evaluator hash differs from the frozen evaluator")

    output.mkdir(parents=True)
    csv_path = output / "test_model_comparison.csv"
    with csv_path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "status": "completed_without_test_tuning",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "candidate_count": len(rows),
        "test_image_count": 733,
        "test_ground_truth_box_count": rows[0]["ground_truth_box_count"],
        "selection_freeze_sha256": sha256(freeze_path),
        "validation_comparison_sha256": sha256(validation_path),
        "test_annotations_sha256": freeze["test_gate"]["test_annotations_sha256"],
        "evaluator_sha256": next(iter(evaluator_hashes)),
        "thresholds_source": "validation selection freeze only",
        "post_test_tuning_performed": False,
        "rows": rows,
        "evidence_files": evidence_files,
        "interpretation_boundary": (
            "Validation-to-test rank changes describe retained split/domain sensitivity. "
            "They do not authorize model reselection, retraining, or a significance claim."
        ),
    }
    json_path = output / "test_model_comparison.json"
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "files": [
            {"path": str(csv_path), "bytes": csv_path.stat().st_size, "sha256": sha256(csv_path)},
            {"path": str(json_path), "bytes": json_path.stat().st_size, "sha256": sha256(json_path)},
        ],
    }
    manifest_path = output / "consolidation_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "rows": len(rows), "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
