#!/usr/bin/env python3
"""Generate COCO predictions directly from a TensorFlow Object Detection checkpoint."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import platform
import sys
import time
import traceback
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checkpoint_hashes(prefix: Path) -> list[dict]:
    paths = sorted(prefix.parent.glob(prefix.name + ".*"))
    if not paths:
        raise FileNotFoundError(f"checkpoint files are missing for {prefix}")
    return [
        {"path": str(path), "bytes": path.stat().st_size, "sha256": file_sha256(path)}
        for path in paths
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--pipeline-config", type=Path, required=True)
    parser.add_argument("--checkpoint-directory", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--image-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--score-floor", type=float, default=0.001)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--progress-every", type=int, default=50)
    arguments = parser.parse_args()

    import numpy as np
    import tensorflow as tf
    from object_detection.builders import model_builder
    from object_detection.utils import config_util

    config_path = arguments.pipeline_config.resolve()
    checkpoint_directory = arguments.checkpoint_directory.resolve()
    annotations = arguments.annotations.resolve()
    image_directory = arguments.image_directory.resolve()
    output = arguments.output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)

    latest = tf.train.latest_checkpoint(str(checkpoint_directory))
    if latest is None:
        raise FileNotFoundError(f"no checkpoint in {checkpoint_directory}")
    checkpoint = Path(latest)
    ground_truth = json.loads(annotations.read_text(encoding="utf-8"))
    images = sorted(ground_truth["images"], key=lambda item: int(item["id"]))
    image_paths = [image_directory / item["file_name"] for item in images]
    missing = [str(path) for path in image_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} COCO images are missing; first: {missing[0]}")

    summary = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "status": "running",
        "model_id": arguments.model_id,
        "framework": "TensorFlow Object Detection API",
        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "python": platform.python_version(),
        "tensorflow": tf.__version__,
        "gpu_devices": [device.name for device in tf.config.list_physical_devices("GPU")],
        "parameters": {
            "score_floor": arguments.score_floor,
            "warmup_iterations": arguments.warmup,
            "batch": 1,
            "image_count": len(images),
            "progress_every_images": arguments.progress_every,
        },
        "pipeline_config_sha256": file_sha256(config_path),
        "annotations_sha256": file_sha256(annotations),
        "checkpoint_prefix": str(checkpoint),
        "checkpoint_files": checkpoint_hashes(checkpoint),
    }
    started = time.monotonic()
    predictions: list[dict] = []
    latency_rows: list[dict] = []
    try:
        configs = config_util.get_configs_from_pipeline_file(str(config_path))
        detection_model = model_builder.build(model_config=configs["model"], is_training=False)
        restore = tf.compat.v2.train.Checkpoint(model=detection_model)
        restore.restore(str(checkpoint)).expect_partial()

        # Validation images retain their native dimensions.  Without an input
        # signature, tf.function creates a separate concrete graph for each
        # new image shape, eventually exhausting WSL memory.  The detector's
        # own preprocessing resizes inputs to the configured model size, so a
        # single dynamic-spatial-dimension graph is the equivalent inference
        # contract and prevents shape-driven retracing.
        @tf.function(
            input_signature=[
                tf.TensorSpec(shape=[1, None, None, 3], dtype=tf.float32)
            ]
        )
        def detect(image_tensor):
            preprocessed, shapes = detection_model.preprocess(image_tensor)
            prediction = detection_model.predict(preprocessed, shapes)
            return detection_model.postprocess(prediction, shapes)

        first = tf.convert_to_tensor(
            np.asarray(tf.keras.utils.load_img(image_paths[0]).convert("RGB")),
            dtype=tf.float32,
        )
        first = tf.expand_dims(first, axis=0)
        for _ in range(arguments.warmup):
            detect(first)
        summary["parameter_count"] = int(
            sum(int(np.prod(variable.shape)) for variable in detection_model.variables)
        )
        summary["trainable_parameter_count"] = int(
            sum(int(np.prod(variable.shape)) for variable in detection_model.trainable_variables)
        )

        for position, (image, path) in enumerate(zip(images, image_paths), start=1):
            rgb = np.asarray(tf.keras.utils.load_img(path).convert("RGB"))
            height, width = rgb.shape[:2]
            tensor = tf.expand_dims(tf.convert_to_tensor(rgb, dtype=tf.float32), axis=0)
            inference_started = time.monotonic()
            detections = detect(tensor)
            inference_ms = (time.monotonic() - inference_started) * 1000.0
            count = int(detections["num_detections"][0].numpy())
            boxes = detections["detection_boxes"][0, :count].numpy()
            scores = detections["detection_scores"][0, :count].numpy()
            classes = detections["detection_classes"][0, :count].numpy().astype(int)
            image_id = int(image["id"])
            latency_rows.append({"image_id": image_id, "inference_ms": inference_ms})
            for box, score, class_index in zip(boxes, scores, classes):
                if float(score) < arguments.score_floor or class_index != 0:
                    continue
                ymin, xmin, ymax, xmax = [float(value) for value in box]
                predictions.append(
                    {
                        "image_id": image_id,
                        "category_id": 1,
                        "bbox": [xmin * width, ymin * height, (xmax - xmin) * width, (ymax - ymin) * height],
                        "score": float(score),
                    }
                )
            if arguments.progress_every > 0 and (
                position % arguments.progress_every == 0 or position == len(images)
            ):
                print(
                    json.dumps(
                        {
                            "event": "prediction_progress",
                            "completed_images": position,
                            "total_images": len(images),
                            "utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                        },
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                    flush=True,
                )

        summary["tf_function_tracing_count"] = int(
            detect.experimental_get_tracing_count()
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
