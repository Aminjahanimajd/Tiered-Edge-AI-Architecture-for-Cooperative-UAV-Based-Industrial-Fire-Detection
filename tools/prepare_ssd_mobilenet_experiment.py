#!/usr/bin/env python3
"""Generate a controlled SSD-MobileNetV2 FPNLite training configuration."""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def training_schedule(image_count, batch_size, epochs):
    if image_count <= 0 or batch_size <= 0 or epochs <= 0:
        raise ValueError("image count, batch size, and epochs must be positive")
    steps_per_epoch = math.ceil(image_count / batch_size)
    total_steps = steps_per_epoch * epochs
    learning_rate = 0.08 * batch_size / 128.0
    return {
        "steps_per_epoch": steps_per_epoch,
        "total_steps": total_steps,
        "learning_rate_base": learning_rate,
        "warmup_learning_rate": learning_rate / 3.0,
        "warmup_steps": steps_per_epoch * 3,
    }


def load_pipeline_message(models_repository, source_config):
    research = models_repository / "research"
    sys.path.insert(0, str(research / "slim"))
    sys.path.insert(0, str(research))
    from google.protobuf import text_format
    from object_detection.protos import pipeline_pb2

    pipeline = pipeline_pb2.TrainEvalPipelineConfig()
    text_format.Merge(source_config.read_text(encoding="utf-8"), pipeline)
    return pipeline, text_format


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-repository", required=True)
    parser.add_argument("--source-config", required=True)
    parser.add_argument("--checkpoint-prefix", required=True)
    parser.add_argument("--label-map", required=True)
    parser.add_argument("--train-record-pattern", required=True)
    parser.add_argument("--validation-record-pattern", required=True)
    parser.add_argument("--output-config", required=True)
    parser.add_argument("--output-summary", required=True)
    parser.add_argument("--train-images", type=int, default=3558)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--epochs", type=int, default=100)
    arguments = parser.parse_args()

    models_repository = Path(arguments.models_repository).resolve()
    source_config = Path(arguments.source_config).resolve()
    checkpoint_prefix = Path(arguments.checkpoint_prefix).resolve()
    label_map = Path(arguments.label_map).resolve()
    output_config = Path(arguments.output_config).resolve()
    output_summary = Path(arguments.output_summary).resolve()
    for required in (
        source_config,
        Path(str(checkpoint_prefix) + ".index"),
        label_map,
    ):
        if not required.is_file():
            raise ValueError("required input is missing: {}".format(required))
    if output_config.exists() or output_summary.exists():
        raise ValueError("refusing to overwrite an experiment configuration")

    pipeline, text_format = load_pipeline_message(models_repository, source_config)
    ssd = pipeline.model.ssd
    resizer = ssd.image_resizer.fixed_shape_resizer
    if ssd.feature_extractor.type != "ssd_mobilenet_v2_fpn_keras":
        raise ValueError("source config is not SSD MobileNet V2 FPNLite")
    if (resizer.height, resizer.width) != (320, 320):
        raise ValueError("source config input is not 320 x 320")

    schedule = training_schedule(
        arguments.train_images, arguments.batch_size, arguments.epochs
    )
    ssd.num_classes = 1
    train = pipeline.train_config
    train.batch_size = arguments.batch_size
    del train.data_augmentation_options[:]
    train.data_augmentation_options.add().random_horizontal_flip.SetInParent()
    train.sync_replicas = False
    train.replicas_to_aggregate = 1
    train.num_steps = schedule["total_steps"]
    train.fine_tune_checkpoint = str(checkpoint_prefix)
    train.fine_tune_checkpoint_type = "detection"
    cosine = train.optimizer.momentum_optimizer.learning_rate.cosine_decay_learning_rate
    cosine.learning_rate_base = schedule["learning_rate_base"]
    cosine.total_steps = schedule["total_steps"]
    cosine.warmup_learning_rate = schedule["warmup_learning_rate"]
    cosine.warmup_steps = schedule["warmup_steps"]

    pipeline.train_input_reader.label_map_path = str(label_map)
    del pipeline.train_input_reader.tf_record_input_reader.input_path[:]
    pipeline.train_input_reader.tf_record_input_reader.input_path.append(
        arguments.train_record_pattern
    )
    validation = pipeline.eval_input_reader[0]
    validation.label_map_path = str(label_map)
    validation.shuffle = False
    validation.num_epochs = 1
    del validation.tf_record_input_reader.input_path[:]
    validation.tf_record_input_reader.input_path.append(
        arguments.validation_record_pattern
    )

    output_config.parent.mkdir(parents=True, exist_ok=True)
    output_config.write_text(text_format.MessageToString(pipeline), encoding="utf-8")
    summary = {
        "schema_version": 1,
        "model_id": "ssd_mobilenet_v2",
        "architecture": "SSD MobileNet V2 FPNLite 320x320",
        "source_config": str(source_config),
        "source_config_sha256": file_sha256(source_config),
        "generated_config": str(output_config),
        "generated_config_sha256": file_sha256(output_config),
        "checkpoint_prefix": str(checkpoint_prefix),
        "checkpoint_index_sha256": file_sha256(Path(str(checkpoint_prefix) + ".index")),
        "label_map_sha256": file_sha256(label_map),
        "train_images": arguments.train_images,
        "batch_size": arguments.batch_size,
        "maximum_epochs": arguments.epochs,
        "schedule": schedule,
        "optimizer": "momentum with cosine decay",
        "momentum": float(train.optimizer.momentum_optimizer.momentum_optimizer_value),
        "augmentation": ["random_horizontal_flip"],
        "selection_data": "validation only",
    }
    output_summary.parent.mkdir(parents=True, exist_ok=True)
    with output_summary.open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
