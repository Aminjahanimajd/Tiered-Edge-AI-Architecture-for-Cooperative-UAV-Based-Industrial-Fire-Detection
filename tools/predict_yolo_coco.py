#!/usr/bin/env python3
"""Generate evidence-captured COCO predictions from one YOLO checkpoint."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import platform
import time
import traceback
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--image-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--input-size", type=int, required=True)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--device", default="0")
    parser.add_argument("--score-floor", type=float, default=0.001)
    parser.add_argument("--warmup", type=int, default=10)
    arguments = parser.parse_args()

    import torch
    import ultralytics
    from ultralytics import YOLO

    checkpoint = arguments.checkpoint.resolve()
    annotations = arguments.annotations.resolve()
    image_directory = arguments.image_directory.resolve()
    output = arguments.output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    if not checkpoint.is_file() or not annotations.is_file() or not image_directory.is_dir():
        raise FileNotFoundError("checkpoint, annotations, or image directory is missing")
    output.mkdir(parents=True)

    ground_truth = json.loads(annotations.read_text(encoding="utf-8"))
    images = sorted(ground_truth["images"], key=lambda item: int(item["id"]))
    paths = [image_directory / item["file_name"] for item in images]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} COCO images are missing; first: {missing[0]}")

    summary = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "status": "running",
        "model_id": arguments.model_id,
        "framework": "Ultralytics YOLO",
        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "ultralytics": ultralytics.__version__,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "parameters": {
            "input_size": arguments.input_size,
            "batch": arguments.batch,
            "device": arguments.device,
            "score_floor": arguments.score_floor,
            "warmup_iterations": arguments.warmup,
            "iou_nms": 0.7,
            "image_count": len(images),
        },
        "checkpoint": {
            "path": str(checkpoint),
            "bytes": checkpoint.stat().st_size,
            "sha256": file_sha256(checkpoint),
        },
        "annotations_sha256": file_sha256(annotations),
    }
    started = time.monotonic()
    predictions: list[dict] = []
    latency_rows: list[dict] = []
    try:
        model = YOLO(str(checkpoint))
        summary["parameter_count"] = sum(parameter.numel() for parameter in model.model.parameters())
        for _ in range(arguments.warmup):
            model.predict(
                source=str(paths[0]),
                imgsz=arguments.input_size,
                conf=arguments.score_floor,
                iou=0.7,
                batch=1,
                device=arguments.device,
                verbose=False,
            )
        for image, path in zip(images, paths):
            result = model.predict(
                source=str(path),
                imgsz=arguments.input_size,
                conf=arguments.score_floor,
                iou=0.7,
                batch=1,
                device=arguments.device,
                verbose=False,
            )[0]
            image_id = int(image["id"])
            latency_rows.append(
                {
                    "image_id": image_id,
                    "preprocess_ms": float(result.speed["preprocess"]),
                    "inference_ms": float(result.speed["inference"]),
                    "postprocess_ms": float(result.speed["postprocess"]),
                }
            )
            for box in result.boxes:
                if int(box.cls.item()) != 0:
                    continue
                x1, y1, x2, y2 = [float(value) for value in box.xyxy[0].tolist()]
                if x2 <= x1 or y2 <= y1:
                    continue
                predictions.append(
                    {
                        "image_id": image_id,
                        "category_id": 1,
                        "bbox": [x1, y1, x2 - x1, y2 - y1],
                        "score": float(box.conf.item()),
                    }
                )

        with (output / "predictions.json").open("x", encoding="utf-8") as stream:
            json.dump(predictions, stream, separators=(",", ":"))
            stream.write("\n")
        with (output / "latency_ms.csv").open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=["image_id", "preprocess_ms", "inference_ms", "postprocess_ms"],
            )
            writer.writeheader()
            writer.writerows(latency_rows)
        summary["status"] = "completed"
        summary["prediction_count"] = len(predictions)
        summary["predictions_sha256"] = file_sha256(output / "predictions.json")
        summary["latency_sha256"] = file_sha256(output / "latency_ms.csv")
    except Exception as error:
        summary["status"] = "failed"
        summary["error"] = repr(error)
        summary["traceback"] = traceback.format_exc()
        raise
    finally:
        summary["ended_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        summary["elapsed_seconds"] = time.monotonic() - started
        with (output / "run_summary.json").open("x", encoding="utf-8") as stream:
            json.dump(summary, stream, indent=2, sort_keys=True)
            stream.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
