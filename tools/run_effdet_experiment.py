#!/usr/bin/env python3
"""Train EfficientDet-Lite0 on the frozen fire-only TFRecords with evidence."""

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import platform
import time
import traceback
from glob import glob
from pathlib import Path


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record_hashes(pattern):
    paths = [Path(path).resolve() for path in sorted(glob(pattern))]
    if not paths:
        raise FileNotFoundError(pattern)
    return [
        {"path": str(path), "bytes": path.stat().st_size, "sha256": file_sha256(path)}
        for path in paths
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-records", required=True)
    parser.add_argument("--train-annotations", required=True)
    parser.add_argument("--validation-records", required=True)
    parser.add_argument("--validation-annotations", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--sanity", action="store_true")
    arguments = parser.parse_args()

    import tensorflow as tf
    import tflite_model_maker
    from tflite_model_maker import object_detector
    from effdet_background_compat import install_background_image_patch

    output_directory = Path(arguments.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=False)
    summary_path = output_directory / "run_summary.json"
    summary = {
        "schema_version": 1,
        "model_id": "efficientdet_lite0",
        "mode": "sanity" if arguments.sanity else "screening",
        "status": "running",
        "started_utc": utc_now(),
        "python": platform.python_version(),
        "tensorflow": tf.__version__,
        "tflite_model_maker": importlib.metadata.version("tflite-model-maker"),
        "gpu_devices": [device.name for device in tf.config.list_physical_devices("GPU")],
        "parameters": {
            "input_size": 320,
            "batch_size": arguments.batch_size,
            "epochs": 1 if arguments.sanity else 100,
            "seed": 20260729,
            "mixed_precision": False,
            "train_size": 8 if arguments.sanity else 3558,
            "validation_size": 8 if arguments.sanity else 700,
        },
        "annotation_hashes": {
            "train": file_sha256(arguments.train_annotations),
            "validation": file_sha256(arguments.validation_annotations),
        },
        "record_shards": {
            "train": record_hashes(arguments.train_records),
            "validation": record_hashes(arguments.validation_records),
        },
    }
    started = time.monotonic()
    try:
        if not summary["gpu_devices"]:
            raise RuntimeError("EfficientDet GPU is unavailable")
        install_background_image_patch()
        train_data = object_detector.DataLoader(
            arguments.train_records,
            summary["parameters"]["train_size"],
            {1: "fire"},
            annotations_json_file=arguments.train_annotations,
        )
        validation_data = object_detector.DataLoader(
            arguments.validation_records,
            summary["parameters"]["validation_size"],
            {1: "fire"},
            annotations_json_file=arguments.validation_annotations,
        )
        specification = object_detector.EfficientDetLite0Spec(
            model_dir=str(output_directory / "checkpoints"),
            epochs=summary["parameters"]["epochs"],
            batch_size=arguments.batch_size,
            hparams={
                "mixed_precision": False,
                "skip_crowd_during_training": False,
            },
            tf_random_seed=20260729,
        )
        model = object_detector.create(
            train_data,
            model_spec=specification,
            validation_data=validation_data,
            epochs=summary["parameters"]["epochs"],
            batch_size=arguments.batch_size,
            train_whole_model=True,
        )
        summary["validation_metrics"] = {
            key: float(value)
            for key, value in model.evaluate(
                validation_data, batch_size=arguments.batch_size
            ).items()
        }
        summary["status"] = "completed"
    except Exception as error:
        summary["status"] = "failed"
        summary["error"] = repr(error)
        summary["traceback"] = traceback.format_exc()
        raise
    finally:
        summary["ended_utc"] = utc_now()
        summary["elapsed_seconds"] = time.monotonic() - started
        with summary_path.open("x", encoding="utf-8") as output:
            json.dump(summary, output, indent=2, sort_keys=True)
            output.write("\n")
        print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
