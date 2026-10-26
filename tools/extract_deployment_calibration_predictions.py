#!/usr/bin/env python3
"""Extract the frozen deployment-calibration subset from retained native predictions."""

from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_RUNS = {
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


def filter_predictions(predictions: list, selected_ids: set[int]) -> list:
    return [
        row for row in predictions
        if int(row["image_id"]) in selected_ids
    ]


def filter_latency_rows(rows: list[dict], selected_ids: set[int]) -> list[dict]:
    selected = [row for row in rows if int(row["image_id"]) in selected_ids]
    observed = {int(row["image_id"]) for row in selected}
    if observed != selected_ids:
        missing = sorted(selected_ids - observed)
        raise ValueError(f"latency rows missing {len(missing)} calibration images")
    return selected


def build(calibration_path: Path, source_root: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    selected_ids = {int(row["image_id"]) for row in calibration["records"]}
    if len(selected_ids) != int(calibration["image_count"]):
        raise ValueError("calibration manifest contains duplicate image IDs")
    output.mkdir(parents=True)
    runs_output = output / "runs"
    runs_output.mkdir()
    records = []

    for model_id, source_name in SOURCE_RUNS.items():
        source = source_root / source_name
        summary_path = source / "run_summary.json"
        predictions_path = source / "predictions.json"
        latency_path = source / "latency_ms.csv"
        for path in (summary_path, predictions_path, latency_path):
            if not path.is_file():
                raise FileNotFoundError(path)
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("status") != "completed":
            raise ValueError(f"{model_id} source run is not completed")
        if summary.get("model_id") != model_id:
            raise ValueError(f"{model_id} source run identity mismatch")
        if summary.get("annotations_sha256") != calibration["annotations_sha256"]:
            raise ValueError(f"{model_id} source annotations differ from calibration source")

        predictions = json.loads(predictions_path.read_text(encoding="utf-8"))
        source_prediction_ids = {int(row["image_id"]) for row in predictions}
        source_annotations = json.loads(
            (ROOT / calibration["annotations_path"]).read_text(encoding="utf-8")
        )
        source_image_ids = {int(row["id"]) for row in source_annotations["images"]}
        if not source_prediction_ids.issubset(source_image_ids):
            raise ValueError(f"{model_id} predictions contain unknown image IDs")
        selected_predictions = filter_predictions(predictions, selected_ids)

        with latency_path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            fieldnames = reader.fieldnames
            if not fieldnames or "image_id" not in fieldnames:
                raise ValueError(f"{model_id} latency schema lacks image_id")
            selected_latency = filter_latency_rows(list(reader), selected_ids)

        model_output = runs_output / model_id
        model_output.mkdir()
        derived_predictions = model_output / "predictions.json"
        derived_latency = model_output / "latency_ms.csv"
        derived_predictions.write_text(
            json.dumps(selected_predictions, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        with derived_latency.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(selected_latency)

        record = {
            "model_id": model_id,
            "status": "COMPLETED_DERIVED_FROM_RETAINED_NATIVE_VALIDATION_RUN",
            "source_run": str(source.relative_to(ROOT)).replace("\\", "/"),
            "source_summary_sha256": sha256(summary_path),
            "source_predictions_sha256": sha256(predictions_path),
            "source_latency_sha256": sha256(latency_path),
            "framework": summary.get("framework"),
            "checkpoint": summary.get("checkpoint"),
            "checkpoint_files": summary.get("checkpoint_files"),
            "calibration_image_count": len(selected_ids),
            "calibration_prediction_count": len(selected_predictions),
            "predictions_path": str(derived_predictions.relative_to(ROOT)).replace("\\", "/"),
            "predictions_sha256": sha256(derived_predictions),
            "latency_path": str(derived_latency.relative_to(ROOT)).replace("\\", "/"),
            "latency_sha256": sha256(derived_latency),
        }
        (model_output / "manifest.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        record["manifest_sha256"] = sha256(model_output / "manifest.json")
        records.append(record)

    manifest = {
        "schema_version": 1,
        "manifest_id": "deployment_calibration_native_predictions_v1",
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "derivation": (
            "Exact image-ID subset of completed retained native-framework validation "
            "predictions; no inference was recomputed and no test data was used."
        ),
        "calibration_manifest": str(calibration_path.relative_to(ROOT)).replace("\\", "/"),
        "calibration_manifest_sha256": sha256(calibration_path),
        "image_count": len(selected_ids),
        "model_count": len(records),
        "models": records,
        "claim_boundary": (
            "Canonical prediction and latency evidence for conversion-fidelity calibration. "
            "These laptop validation rows are not exact-device deployment measurements."
        ),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "PASS", "models": len(records), "images": len(selected_ids), "output": str(output)}, indent=2))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--calibration",
        type=Path,
        default=ROOT / "config" / "deployment_calibration_manifest_v1.json",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=ROOT / "artifacts" / "experiments" / "model_screening_v1" / "validation_comparison_v1" / "runs",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.calibration.resolve(), args.source_root.resolve(), args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
