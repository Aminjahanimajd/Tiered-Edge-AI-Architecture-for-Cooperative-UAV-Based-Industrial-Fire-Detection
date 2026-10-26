#!/usr/bin/env python3
"""Restore and export one EfficientDet Model Maker checkpoint with evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import time
import traceback
from glob import glob
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def matching_hashes(pattern: str) -> list[dict]:
    paths = [Path(item).resolve() for item in sorted(glob(pattern))]
    if not paths:
        raise FileNotFoundError(pattern)
    return [
        {"path": str(path), "bytes": path.stat().st_size, "sha256": file_sha256(path)}
        for path in paths
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--validation-records", required=True)
    parser.add_argument("--validation-annotations", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--steps-per-epoch", type=int, default=889)
    arguments = parser.parse_args()

    import tensorflow as tf
    from effdet_background_compat import install_background_image_patch
    from tensorflow_examples.lite.model_maker.third_party.efficientdet.keras import train
    from tflite_model_maker import object_detector
    from tflite_model_maker.config import ExportFormat

    checkpoint = arguments.checkpoint.resolve()
    annotation_path = arguments.validation_annotations.resolve()
    output = arguments.output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    checkpoint_files = matching_hashes(str(checkpoint) + ".*")
    record_files = matching_hashes(arguments.validation_records)
    output.mkdir(parents=True)
    summary_path = output / "export_summary.json"
    summary = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "status": "running",
        "model_id": "efficientdet_lite0",
        "framework": "TensorFlow Lite Model Maker",
        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "python": platform.python_version(),
        "tensorflow": tf.__version__,
        "checkpoint_prefix": str(checkpoint),
        "checkpoint_files": checkpoint_files,
        "validation_annotations_sha256": file_sha256(annotation_path),
        "validation_record_files": record_files,
        "parameters": {
            "input_size": 320,
            "batch_size": arguments.batch_size,
            "validation_size": 700,
            "steps_per_epoch": arguments.steps_per_epoch,
            "mixed_precision": False,
            "metadata_embedded": False,
        },
    }
    started = time.monotonic()
    try:
        install_background_image_patch()
        validation_data = object_detector.DataLoader(
            arguments.validation_records,
            700,
            {1: "fire"},
            annotations_json_file=str(annotation_path),
        )
        specification = object_detector.EfficientDetLite0Spec(
            model_dir=str(output / "restore_workspace"),
            epochs=100,
            batch_size=arguments.batch_size,
            hparams={"mixed_precision": False, "skip_crowd_during_training": False},
            tf_random_seed=20260729,
        )
        specification.config.var_freeze_expr = None
        detector = object_detector.ObjectDetector(
            specification, validation_data.label_map, validation_data
        )
        with specification.ds_strategy.scope():
            detector.create_model()
            _, validation_steps, validation_json = detector._get_dataset_and_steps(
                validation_data, arguments.batch_size, is_training=False
            )
            specification.config.update(
                dict(
                    steps_per_epoch=arguments.steps_per_epoch,
                    eval_samples=arguments.batch_size * validation_steps,
                    val_json_file=validation_json,
                    batch_size=arguments.batch_size,
                )
            )
            train.setup_model(detector.model, specification.config)
            restored = detector.model.load_weights(str(checkpoint))
            restored.expect_partial()
        summary["parameter_count"] = int(detector.model.count_params())
        summary["trainable_parameter_count"] = int(
            sum(int(tf.size(variable).numpy()) for variable in detector.model.trainable_variables)
        )
        detector.export(
            str(output),
            tflite_filename="efficientdet_lite0.tflite",
            label_filename="labels.txt",
            export_format=[ExportFormat.TFLITE, ExportFormat.LABEL],
            with_metadata=False,
        )
        artifacts = []
        for name in ("efficientdet_lite0.tflite", "labels.txt"):
            path = output / name
            artifacts.append(
                {"path": str(path), "bytes": path.stat().st_size, "sha256": file_sha256(path)}
            )
        summary["artifacts"] = artifacts
        summary["status"] = "completed"
    except Exception as error:
        summary["status"] = "failed"
        summary["error"] = repr(error)
        summary["traceback"] = traceback.format_exc()
        raise
    finally:
        summary["ended_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        summary["elapsed_seconds"] = time.monotonic() - started
        with summary_path.open("x", encoding="utf-8") as stream:
            json.dump(summary, stream, indent=2, sort_keys=True)
            stream.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
