#!/usr/bin/env python3
"""Export the frozen COCO materialization to verified TFRecord shards."""

import argparse
import hashlib
import json
import sys
from pathlib import Path


SPLIT_SETTINGS = {
    "train": ("coco_train.record", 16),
    "valid": ("coco_val.record", 4),
    "test": ("coco_testdev.record", 4),
}


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def label_map_text():
    return "item {\n  id: 1\n  name: 'fire'\n}\n"


def validate_coco_export(coco_directory, summary):
    for split in SPLIT_SETTINGS:
        labels = coco_directory / split / "labels.json"
        expected = summary["split_results"][split]["labels_json_sha256"]
        if file_sha256(labels) != expected:
            raise ValueError("COCO labels hash mismatch for {}".format(split))


def load_official_converter(models_repository):
    research = models_repository / "research"
    required = research / "object_detection" / "dataset_tools" / "create_coco_tf_record.py"
    if not required.is_file():
        raise ValueError("pinned Object Detection API source is missing")
    sys.path.insert(0, str(research / "slim"))
    sys.path.insert(0, str(research))
    from object_detection.dataset_tools.create_coco_tf_record import (
        _create_tf_record_from_coco_annotations,
    )

    return _create_tf_record_from_coco_annotations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coco-directory", required=True)
    parser.add_argument("--models-repository", required=True)
    parser.add_argument("--output-directory", required=True)
    arguments = parser.parse_args()

    import tensorflow as tf

    coco_directory = Path(arguments.coco_directory).resolve()
    models_repository = Path(arguments.models_repository).resolve()
    output_directory = Path(arguments.output_directory).resolve()
    summary_path = coco_directory / "coco_export_summary.json"
    with summary_path.open("r", encoding="utf-8") as source:
        coco_summary = json.load(source)
    validate_coco_export(coco_directory, coco_summary)
    converter = load_official_converter(models_repository)
    output_directory.mkdir(parents=True, exist_ok=False)

    label_map = output_directory / "fire.pbtxt"
    label_map.write_text(label_map_text(), encoding="utf-8")
    split_results = {}
    for split, (base_name, shard_count) in SPLIT_SETTINGS.items():
        converter(
            str(coco_directory / split / "labels.json"),
            str(coco_directory / split / "images"),
            str(output_directory / base_name),
            include_masks=False,
            num_shards=shard_count,
        )
        shards = sorted(output_directory.glob(base_name + "-*"))
        if len(shards) != shard_count:
            raise ValueError("unexpected shard count for {}".format(split))
        record_count = sum(
            1 for _ in tf.data.TFRecordDataset([str(path) for path in shards])
        )
        expected_count = coco_summary["split_results"][split]["images"]
        if record_count != expected_count:
            raise ValueError(
                "TFRecord count mismatch for {}: {} != {}".format(
                    split, record_count, expected_count
                )
            )
        split_results[split] = {
            "record_count": record_count,
            "annotation_count": coco_summary["split_results"][split]["annotations"],
            "shard_count": len(shards),
            "shards": [
                {
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": file_sha256(path),
                }
                for path in shards
            ],
        }

    output_summary = {
        "schema_version": 1,
        "dataset_id": coco_summary["dataset_id"],
        "source_coco_summary": str(summary_path),
        "source_coco_summary_sha256": file_sha256(summary_path),
        "object_detection_repository": str(models_repository),
        "label_map": str(label_map),
        "label_map_sha256": file_sha256(label_map),
        "split_results": split_results,
    }
    destination = output_directory / "tfrecord_export_summary.json"
    with destination.open("x", encoding="utf-8") as output:
        json.dump(output_summary, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(output_summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
