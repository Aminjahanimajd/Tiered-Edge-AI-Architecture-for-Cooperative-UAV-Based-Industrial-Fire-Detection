#!/usr/bin/env python3
"""Run the frozen YOLO calibration images and compare ONNX to native rows."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def xywh_iou(left, right) -> float:
    lx1, ly1, lw, lh = map(float, left)
    rx1, ry1, rw, rh = map(float, right)
    lx2, ly2, rx2, ry2 = lx1 + lw, ly1 + lh, rx1 + rw, ry1 + rh
    ix1, iy1, ix2, iy2 = max(lx1, rx1), max(ly1, ry1), min(lx2, rx2), min(ly2, ry2)
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = lw * lh + rw * rh - intersection
    return intersection / union if union > 0 else 0.0


def match_predictions(native: list[dict], converted: list[dict], threshold=0.5) -> dict:
    native_by_image, converted_by_image = defaultdict(list), defaultdict(list)
    for row in native:
        native_by_image[int(row["image_id"])].append(row)
    for row in converted:
        converted_by_image[int(row["image_id"])].append(row)
    matched, confidence_differences = 0, []
    for image_id in sorted(set(native_by_image) | set(converted_by_image)):
        available = set(range(len(converted_by_image[image_id])))
        for source in sorted(native_by_image[image_id], key=lambda row: -float(row["score"])):
            choices = [
                (xywh_iou(source["bbox"], converted_by_image[image_id][index]["bbox"]), index)
                for index in available
                if int(source["category_id"]) == int(converted_by_image[image_id][index]["category_id"])
            ]
            if not choices:
                continue
            overlap, index = max(choices)
            if overlap >= threshold:
                available.remove(index)
                matched += 1
                confidence_differences.append(abs(
                    float(source["score"]) - float(converted_by_image[image_id][index]["score"])
                ))
    denominator = max(len(native), len(converted), 1)
    return {
        "native_detection_count": len(native),
        "converted_detection_count": len(converted),
        "matched_detection_count": matched,
        "detection_match_rate": matched / denominator,
        "mean_absolute_confidence_difference": (
            sum(confidence_differences) / len(confidence_differences)
            if confidence_differences else None
        ),
        "iou_threshold": float(threshold),
    }


def predict(model_path: Path, model_row: dict, calibration: dict) -> list[dict]:
    from ultralytics import YOLO
    image_root = ROOT / calibration["image_root"]
    records = calibration["records"]
    paths = [str(image_root / row["file_name"]) for row in records]
    model = YOLO(str(model_path), task="detect")
    results = []
    # Fixed-shape exports accept one image per invocation. Passing a Python
    # list to this Ultralytics version constructs a 64-image tensor before the
    # ONNX session and violates the frozen batch dimension.
    for path in paths:
        result = model.predict(
            source=path,
            imgsz=int(model_row["input_size"]),
            conf=0.001,
            iou=0.7,
            batch=1,
            device="cpu",
            verbose=False,
            stream=False,
        )
        if len(result) != 1:
            raise RuntimeError("expected one ONNX result per calibration image")
        results.append(result[0])
    output = []
    for metadata, result in zip(records, results, strict=True):
        boxes = result.boxes
        for xyxy, score, class_id in zip(
            boxes.xyxy.cpu().tolist(),
            boxes.conf.cpu().tolist(),
            boxes.cls.cpu().tolist(),
            strict=True,
        ):
            x1, y1, x2, y2 = map(float, xyxy)
            output.append({
                "image_id": int(metadata["image_id"]),
                "category_id": int(class_id) + 1,
                "bbox": [x1, y1, x2 - x1, y2 - y1],
                "score": float(score),
            })
    return output


def run(candidate_root: Path, calibration_path: Path, native_root: Path, output: Path):
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    candidate_manifest_path = candidate_root / "manifest.json"
    candidate_manifest = json.loads(candidate_manifest_path.read_text(encoding="utf-8"))
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    output.mkdir(parents=True)
    records = []
    for model_row in candidate_manifest["models"]:
        model_id = model_row["model_id"]
        model_path = ROOT / model_row["onnx_path"]
        if sha256(model_path) != model_row["onnx_sha256"]:
            raise ValueError(f"ONNX hash mismatch for {model_id}")
        native_path = native_root / "runs" / model_id / "predictions.json"
        native = json.loads(native_path.read_text(encoding="utf-8"))
        converted = predict(model_path, model_row, calibration)
        model_output = output / model_id
        model_output.mkdir()
        prediction_path = model_output / "predictions.json"
        prediction_path.write_text(
            json.dumps(converted, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        comparison = match_predictions(native, converted, 0.5)
        comparison["confidence_tolerance"] = 0.02
        comparison["minimum_match_rate"] = 0.95
        confidence = comparison["mean_absolute_confidence_difference"]
        passed = (
            comparison["detection_match_rate"] >= 0.95
            and confidence is not None and confidence <= 0.02
        )
        record = {
            "model_id": model_id,
            "status": "PASS" if passed else "FIDELITY_FAILED",
            "onnx_sha256": model_row["onnx_sha256"],
            "native_predictions_sha256": sha256(native_path),
            "converted_predictions_sha256": sha256(prediction_path),
            "comparison": comparison,
            "preprocessing": "Ultralytics letterbox through YOLO.predict",
            "decoding": "Ultralytics detection head and NMS; conf=0.001, IoU=0.7",
            "class_mapping": "zero-based model class plus one to COCO category ID",
        }
        (model_output / "manifest.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        record["manifest_sha256"] = sha256(model_output / "manifest.json")
        records.append(record)
    manifest = {
        "schema_version": 1,
        "run_type": "yolo_onnx_conversion_fidelity",
        "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "candidate_manifest_sha256": sha256(candidate_manifest_path),
        "calibration_manifest_sha256": sha256(calibration_path),
        "native_manifest_sha256": sha256(native_root / "manifest.json"),
        "image_count": int(calibration["image_count"]),
        "models": records,
        "status": "PASS" if all(row["status"] == "PASS" for row in records) else "FIDELITY_FAILED",
        "claim_boundary": "Laptop conversion-fidelity comparison only; no Jetson or VOXL deployment or latency claim.",
        "generator_sha256": sha256(Path(__file__)),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--calibration", type=Path,
        default=ROOT / "config/deployment_calibration_manifest_v1.json",
    )
    parser.add_argument(
        "--native-root", type=Path,
        default=ROOT / "artifacts/experiments/deployment_calibration_native_v1",
    )
    args = parser.parse_args(argv)
    result = run(
        args.candidate_root.resolve(), args.calibration.resolve(),
        args.native_root.resolve(), args.output.resolve(),
    )
    print(json.dumps({"status": result["status"], "models": [
        {"model_id": row["model_id"], "status": row["status"], **row["comparison"]}
        for row in result["models"]
    ]}, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
