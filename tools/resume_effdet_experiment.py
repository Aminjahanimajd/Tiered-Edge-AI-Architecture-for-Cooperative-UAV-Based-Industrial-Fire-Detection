#!/usr/bin/env python3
"""Resume the interrupted EfficientDet screening run with full optimizer state."""

import argparse
import datetime as dt
import hashlib
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
    parser.add_argument("--resume-checkpoint", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--epochs", type=int, default=100)
    arguments = parser.parse_args()

    import tensorflow as tf
    from tflite_model_maker import object_detector
    from effdet_background_compat import install_background_image_patch
    from tensorflow_examples.lite.model_maker.third_party.efficientdet.keras import train
    from tensorflow_examples.lite.model_maker.third_party.efficientdet.keras import train_lib

    checkpoint = Path(arguments.resume_checkpoint).resolve()
    checkpoint_index = Path(str(checkpoint) + ".index")
    checkpoint_data = Path(str(checkpoint) + ".data-00000-of-00001")
    if not checkpoint_index.is_file() or not checkpoint_data.is_file():
        raise FileNotFoundError(f"incomplete checkpoint prefix: {checkpoint}")

    output_directory = Path(arguments.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=False)
    summary_path = output_directory / "run_summary.json"
    summary = {
        "schema_version": 1,
        "model_id": "efficientdet_lite0",
        "mode": "screening_checkpoint_resume",
        "status": "running",
        "started_utc": utc_now(),
        "python": platform.python_version(),
        "tensorflow": tf.__version__,
        "gpu_devices": [device.name for device in tf.config.list_physical_devices("GPU")],
        "parameters": {
            "input_size": 320,
            "batch_size": arguments.batch_size,
            "target_epochs": arguments.epochs,
            "seed": 20260729,
            "mixed_precision": False,
            "train_size": 3558,
            "validation_size": 700,
        },
        "resume_checkpoint": {
            "prefix": str(checkpoint),
            "index_sha256": file_sha256(checkpoint_index),
            "data_sha256": file_sha256(checkpoint_data),
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
            epochs=arguments.epochs,
            batch_size=arguments.batch_size,
            hparams={"mixed_precision": False, "skip_crowd_during_training": False},
            tf_random_seed=20260729,
        )
        specification.config.var_freeze_expr = None
        detector = object_detector.ObjectDetector(
            specification, train_data.label_map, train_data
        )
        with specification.ds_strategy.scope():
            detector.create_model()
            train_ds, steps_per_epoch, _ = detector._get_dataset_and_steps(
                train_data, arguments.batch_size, is_training=True
            )
            validation_ds, validation_steps, validation_json = detector._get_dataset_and_steps(
                validation_data, arguments.batch_size, is_training=False
            )
            specification.config.update(
                dict(
                    steps_per_epoch=steps_per_epoch,
                    eval_samples=arguments.batch_size * validation_steps,
                    val_json_file=validation_json,
                    batch_size=arguments.batch_size,
                )
            )
            train.setup_model(detector.model, specification.config)
            train.init_experimental(specification.config)
            restore_status = detector.model.load_weights(str(checkpoint))
            restore_status.expect_partial()
            optimizer_iterations = int(detector.model.optimizer.iterations.numpy())
            initial_epoch, partial_steps = divmod(optimizer_iterations, steps_per_epoch)
            if partial_steps:
                raise RuntimeError(
                    f"checkpoint is not epoch-aligned: {optimizer_iterations} iterations, "
                    f"{steps_per_epoch} steps/epoch"
                )
            if initial_epoch <= 0 or initial_epoch >= arguments.epochs:
                raise RuntimeError(
                    f"invalid restored epoch {initial_epoch} for target {arguments.epochs}"
                )
            summary["resume_state"] = {
                "optimizer_iterations": optimizer_iterations,
                "steps_per_epoch": steps_per_epoch,
                "initial_epoch": initial_epoch,
                "remaining_epochs": arguments.epochs - initial_epoch,
            }
            callbacks = train_lib.get_callbacks(
                specification.config.as_dict(), validation_ds
            )
            detector.model.fit(
                train_ds,
                initial_epoch=initial_epoch,
                epochs=arguments.epochs,
                steps_per_epoch=steps_per_epoch,
                callbacks=callbacks,
                validation_data=validation_ds,
                validation_steps=validation_steps,
            )
        summary["validation_metrics"] = {
            key: float(value)
            for key, value in detector.evaluate(
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
