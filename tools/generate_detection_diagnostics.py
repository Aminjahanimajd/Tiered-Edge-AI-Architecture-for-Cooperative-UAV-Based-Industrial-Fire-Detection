#!/usr/bin/env python3
"""Generate frozen six-model PR and one-class detection-outcome figures."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib.pyplot as plt
import numpy as np
from pycocotools.coco import COCO
from pycocotools.cocoeval import COCOeval


MODELS = (
    ("yolov8n_416", "YOLOv8n-416"),
    ("yolov8n_640", "YOLOv8n-640"),
    ("yolov8s_416", "YOLOv8s-416"),
    ("yolov8s_640", "YOLOv8s-640"),
    ("ssd_mobilenet_v2_fpnlite_320", "SSD MobileNet-320"),
    ("efficientdet_lite0_320", "EfficientDet-320"),
)

VALIDATION_DIRECTORY_OVERRIDES = {
    "yolov8n_416": "yolov8n_416_timing_retry2",
    "ssd_mobilenet_v2_fpnlite_320": "ssd_mobilenet_v2_fpnlite_320_retry2_dynamic_signature",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def coco_pr_curve(annotations: Path, predictions: Path) -> tuple[np.ndarray, np.ndarray]:
    with contextlib.redirect_stdout(io.StringIO()):
        ground_truth = COCO(str(annotations))
        prediction_data = json.loads(predictions.read_text(encoding="utf-8"))
        detections = ground_truth.loadRes(prediction_data)
        evaluator = COCOeval(ground_truth, detections, "bbox")
        evaluator.evaluate()
        evaluator.accumulate()

    iou_index = int(np.argmin(np.abs(evaluator.params.iouThrs - 0.50)))
    # precision dimensions: IoU, recall, category, area, max detections.
    precision = evaluator.eval["precision"][iou_index, :, 0, 0, 2]
    recall = evaluator.params.recThrs
    valid = precision >= 0.0
    return recall[valid], precision[valid]


def save_figure(figure: plt.Figure, output_base: Path) -> list[Path]:
    outputs = [output_base.with_suffix(".pdf"), output_base.with_suffix(".png")]
    figure.savefig(outputs[0], bbox_inches="tight")
    figure.savefig(outputs[1], dpi=220, bbox_inches="tight")
    plt.close(figure)
    return outputs


def generate_pr_figure(repo: Path, output: Path) -> tuple[list[Path], list[dict]]:
    experiment = repo / "artifacts/experiments/model_screening_v1"
    split_config = {
        "validation": (
            repo / "artifacts/training/fire_only_curated_v7_coco/valid/labels.json",
            experiment / "validation_comparison_v1/runs",
        ),
        "test": (
            repo / "artifacts/training/fire_only_curated_v7_coco/test/labels.json",
            experiment / "test_comparison_v1/runs",
        ),
    }
    figure, axes = plt.subplots(1, 2, figsize=(11.2, 4.6), sharex=True, sharey=True)
    colors = plt.get_cmap("tab10").colors
    inputs: list[dict] = []
    for axis, (split, (annotations, runs)) in zip(axes, split_config.items()):
        for index, (model_id, label) in enumerate(MODELS):
            directory = (
                VALIDATION_DIRECTORY_OVERRIDES.get(model_id, model_id)
                if split == "validation"
                else model_id
            )
            predictions = runs / directory / "predictions_evaluable.json"
            recall, precision = coco_pr_curve(annotations, predictions)
            axis.plot(recall, precision, linewidth=1.8, color=colors[index], label=label)
            inputs.append(
                {
                    "split": split,
                    "model_id": model_id,
                    "annotations_sha256": sha256(annotations),
                    "predictions_sha256": sha256(predictions),
                }
            )
        axis.set_title(f"{split.capitalize()} at IoU 0.50")
        axis.set_xlabel("Recall")
        axis.grid(alpha=0.25)
        axis.set_xlim(0.0, 1.0)
        axis.set_ylim(0.0, 1.02)
    axes[0].set_ylabel("Interpolated precision")
    handles, labels = axes[1].get_legend_handles_labels()
    figure.legend(handles, labels, loc="lower center", ncol=3, frameon=False)
    figure.subplots_adjust(bottom=0.22, wspace=0.12)
    return save_figure(figure, output / "model_pr_curves_iou50"), inputs


def generate_outcome_figure(repo: Path, output: Path) -> tuple[list[Path], list[dict]]:
    runs = repo / "artifacts/experiments/model_screening_v1/test_comparison_v1/runs"
    figure, axes = plt.subplots(2, 3, figsize=(10.6, 6.6))
    inputs: list[dict] = []
    for axis, (model_id, label) in zip(axes.flat, MODELS):
        metrics_path = runs / model_id / "metrics.json"
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))["thresholded_iou50"]
        matrix = np.array(
            [[float(metrics["tp"]), float(metrics["fn"])], [float(metrics["fp"]), np.nan]]
        )
        masked = np.ma.masked_invalid(matrix)
        axis.imshow(masked, cmap="Blues", vmin=0.0, vmax=float(np.nanmax(matrix)))
        for row in range(2):
            for column in range(2):
                value = matrix[row, column]
                text = "N/A" if np.isnan(value) else str(int(value))
                axis.text(column, row, text, ha="center", va="center", fontsize=11)
        axis.set_title(label, fontsize=10)
        axis.set_xticks((0, 1))
        axis.set_xticklabels(("Fire detection", "No match"), rotation=15, ha="right")
        axis.set_yticks((0, 1))
        axis.set_yticklabels(("Fire object", "Unmatched/background"))
        inputs.append(
            {
                "model_id": model_id,
                "metrics_sha256": sha256(metrics_path),
                "threshold": metrics["threshold"],
                "tp": metrics["tp"],
                "fp": metrics["fp"],
                "fn": metrics["fn"],
            }
        )
    figure.suptitle(
        "One-time test detection outcomes at validation-frozen thresholds\n"
        "True negatives are undefined for exhaustive object-detection background",
        fontsize=12,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.92))
    return save_figure(figure, output / "test_detection_outcome_matrices"), inputs


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    output = repo / "thesis/generated"
    output.mkdir(parents=True, exist_ok=True)

    generated: list[Path] = []
    pr_files, pr_inputs = generate_pr_figure(repo, output)
    generated.extend(pr_files)
    outcome_files, outcome_inputs = generate_outcome_figure(repo, output)
    generated.extend(outcome_files)

    manifest = {
        "schema_version": 1,
        "status": "generated_from_frozen_validation_and_one_time_test_outputs",
        "pr_definition": "COCO interpolated precision at IoU 0.50, area=all, maxDets=100",
        "outcome_definition": "one-class object-detection TP/FN/FP; exhaustive TN undefined",
        "pr_inputs": pr_inputs,
        "outcome_inputs": outcome_inputs,
        "files": [
            {
                "path": path.resolve().relative_to(repo).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in generated
        ],
    }
    manifest_path = output / "detection_diagnostics_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
