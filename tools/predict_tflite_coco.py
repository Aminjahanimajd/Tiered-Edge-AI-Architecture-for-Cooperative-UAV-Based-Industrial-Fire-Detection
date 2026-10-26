#!/usr/bin/env python3
"""Generate evidence-captured COCO predictions from a TFLite detector."""

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


def dequantize(array, detail):
    import numpy as np

    scale, zero_point = detail["quantization"]
    if scale and np.issubdtype(array.dtype, np.integer):
        return (array.astype(np.float32) - float(zero_point)) * float(scale)
    return array.astype(np.float32, copy=False)


def prepare_input(
    rgb,
    detail,
    float_input_scale: float,
    integer_input_mode: str = "raw_pixels",
    float_input_offset: float = 0.0,
):
    import numpy as np

    dtype = detail["dtype"]
    if np.issubdtype(dtype, np.floating):
        return (
            rgb.astype(dtype) * float_input_scale + float_input_offset
        )[None, ...]
    if integer_input_mode == "raw_pixels":
        limits = np.iinfo(dtype)
        return np.clip(rgb, limits.min, limits.max).astype(dtype)[None, ...]
    if integer_input_mode != "quantize_scaled":
        raise ValueError(f"unsupported integer input mode: {integer_input_mode}")
    scale, zero_point = detail["quantization"]
    if scale:
        real_values = (
            rgb.astype(np.float32) * float_input_scale + float_input_offset
        )
        quantized = np.rint(real_values / float(scale) + float(zero_point))
        limits = np.iinfo(dtype)
        return np.clip(quantized, limits.min, limits.max).astype(dtype)[None, ...]
    return rgb.astype(dtype)[None, ...]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--image-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--boxes-tensor-index", type=int, required=True)
    parser.add_argument("--classes-tensor-index", type=int, required=True)
    parser.add_argument("--scores-tensor-index", type=int, required=True)
    parser.add_argument("--count-tensor-index", type=int, required=True)
    parser.add_argument("--class-id-offset", type=int, default=1)
    parser.add_argument("--score-floor", type=float, default=0.001)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--float-input-scale", type=float, default=1.0)
    parser.add_argument("--float-input-offset", type=float, default=0.0)
    parser.add_argument(
        "--resize-backend",
        choices=("pil_bilinear", "tensorflow_bilinear"),
        default="pil_bilinear",
    )
    parser.add_argument(
        "--integer-input-mode",
        choices=("raw_pixels", "quantize_scaled"),
        default="raw_pixels",
    )
    arguments = parser.parse_args()

    import numpy as np
    import tensorflow as tf
    from PIL import Image

    model = arguments.model.resolve()
    annotations = arguments.annotations.resolve()
    image_directory = arguments.image_directory.resolve()
    output = arguments.output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    if not model.is_file() or not annotations.is_file() or not image_directory.is_dir():
        raise FileNotFoundError("model, annotations, or image directory is missing")
    output.mkdir(parents=True)

    ground_truth = json.loads(annotations.read_text(encoding="utf-8"))
    images = sorted(ground_truth["images"], key=lambda item: int(item["id"]))
    paths = [image_directory / item["file_name"] for item in images]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} COCO images are missing; first: {missing[0]}")

    interpreter = tf.lite.Interpreter(model_path=str(model))
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    if len(input_details) != 1:
        raise RuntimeError(f"expected one model input, found {len(input_details)}")
    input_detail = input_details[0]
    _, input_height, input_width, channels = [int(value) for value in input_detail["shape"]]
    if channels != 3:
        raise RuntimeError(f"expected RGB input, found shape {input_detail['shape']}")
    output_by_index = {int(item["index"]): item for item in interpreter.get_output_details()}
    requested = {
        "boxes": arguments.boxes_tensor_index,
        "classes": arguments.classes_tensor_index,
        "scores": arguments.scores_tensor_index,
        "count": arguments.count_tensor_index,
    }
    unknown = {name: index for name, index in requested.items() if index not in output_by_index}
    if unknown:
        raise ValueError(f"requested output tensor indices are absent: {unknown}")

    summary = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "status": "running",
        "model_id": arguments.model_id,
        "framework": "TensorFlow Lite Interpreter",
        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "python": platform.python_version(),
        "tensorflow": tf.__version__,
        "model": {"path": str(model), "bytes": model.stat().st_size, "sha256": file_sha256(model)},
        "annotations_sha256": file_sha256(annotations),
        "parameters": {
            "input_size": [input_height, input_width],
            "batch": 1,
            "warmup_iterations": arguments.warmup,
            "score_floor": arguments.score_floor,
            "class_id_offset": arguments.class_id_offset,
            "float_input_scale": arguments.float_input_scale,
            "float_input_offset": arguments.float_input_offset,
            "integer_input_mode": arguments.integer_input_mode,
            "resize_backend": arguments.resize_backend,
            "image_count": len(images),
            "output_tensor_indices": requested,
        },
    }
    started = time.monotonic()
    predictions: list[dict] = []
    latency_rows: list[dict] = []

    def read_rgb(path: Path):
        with Image.open(path) as source:
            rgb = np.asarray(source.convert("RGB"))
        if arguments.resize_backend == "tensorflow_bilinear":
            return tf.image.resize(
                rgb, [input_height, input_width], method="bilinear", antialias=False
            ).numpy()
        return np.asarray(
            Image.fromarray(rgb).resize(
                (input_width, input_height), Image.Resampling.BILINEAR
            )
        )

    try:
        warmup_input = prepare_input(
            read_rgb(paths[0]), input_detail, arguments.float_input_scale,
            arguments.integer_input_mode, arguments.float_input_offset
        )
        for _ in range(arguments.warmup):
            interpreter.set_tensor(int(input_detail["index"]), warmup_input)
            interpreter.invoke()

        for image, path in zip(images, paths):
            with Image.open(path) as source:
                source_width, source_height = source.size
            model_input = prepare_input(
                read_rgb(path), input_detail, arguments.float_input_scale,
                arguments.integer_input_mode, arguments.float_input_offset
            )
            interpreter.set_tensor(int(input_detail["index"]), model_input)
            inference_started = time.monotonic()
            interpreter.invoke()
            inference_ms = (time.monotonic() - inference_started) * 1000.0
            tensors = {
                name: dequantize(interpreter.get_tensor(index), output_by_index[index])
                for name, index in requested.items()
            }
            count = min(int(round(float(tensors["count"].reshape(-1)[0]))), tensors["boxes"].reshape(-1, 4).shape[0])
            boxes = tensors["boxes"].reshape(-1, 4)[:count]
            classes = tensors["classes"].reshape(-1)[:count]
            scores = tensors["scores"].reshape(-1)[:count]
            image_id = int(image["id"])
            latency_rows.append({"image_id": image_id, "inference_ms": inference_ms})
            for box, class_value, score in zip(boxes, classes, scores):
                if float(score) < arguments.score_floor:
                    continue
                category_id = int(round(float(class_value))) + arguments.class_id_offset
                if category_id != 1:
                    continue
                ymin, xmin, ymax, xmax = [float(value) for value in box]
                x1 = min(max(xmin, 0.0), 1.0) * source_width
                y1 = min(max(ymin, 0.0), 1.0) * source_height
                x2 = min(max(xmax, 0.0), 1.0) * source_width
                y2 = min(max(ymax, 0.0), 1.0) * source_height
                if x2 <= x1 or y2 <= y1:
                    continue
                predictions.append(
                    {
                        "image_id": image_id,
                        "category_id": category_id,
                        "bbox": [x1, y1, x2 - x1, y2 - y1],
                        "score": float(score),
                    }
                )

        with (output / "predictions.json").open("x", encoding="utf-8") as stream:
            json.dump(predictions, stream, separators=(",", ":"))
            stream.write("\n")
        with (output / "latency_ms.csv").open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["image_id", "inference_ms"])
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
