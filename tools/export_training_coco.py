#!/usr/bin/env python3
"""Export the frozen manifest to deterministic per-split COCO directories."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

try:
    from materialize_training_dataset import file_sha256, materialized_name
except ImportError:
    from tools.materialize_training_dataset import file_sha256, materialized_name


def yolo_row_to_coco(row, image_width, image_height):
    fields = row.split()
    if len(fields) != 5 or fields[0] != "0":
        raise ValueError("expected one-class five-field YOLO row")
    center_x, center_y, width, height = map(float, fields[1:])
    box_width = width * image_width
    box_height = height * image_height
    left = (center_x - width / 2.0) * image_width
    top = (center_y - height / 2.0) * image_height
    return [left, top, box_width, box_height]


def build_split(records, split, output_directory):
    from PIL import Image

    split_records = sorted(
        (record for record in records if record["split"] == split),
        key=lambda record: record["record_id"],
    )
    split_directory = output_directory / split
    image_directory = split_directory / "images"
    image_directory.mkdir(parents=True, exist_ok=False)
    images = []
    annotations = []
    annotation_id = 1
    for image_id, record in enumerate(split_records, start=1):
        source = Path(record["image_path"])
        name = materialized_name(record)
        destination = image_directory / name
        shutil.copy2(str(source), str(destination))
        with Image.open(destination) as image:
            width, height = image.size
        images.append(
            {
                "id": image_id,
                "file_name": name,
                "width": width,
                "height": height,
                "record_id": record["record_id"],
            }
        )
        for row in record.get("derived_label_rows", []):
            bbox = yolo_row_to_coco(row, width, height)
            annotations.append(
                {
                    "id": annotation_id,
                    "image_id": image_id,
                    "category_id": 1,
                    "bbox": bbox,
                    "area": bbox[2] * bbox[3],
                    "iscrowd": 0,
                }
            )
            annotation_id += 1
    labels = {
        "info": {"description": "fire_only_curated_manifest_v7", "version": "7"},
        "licenses": [],
        "categories": [{"id": 1, "name": "fire", "supercategory": "hazard"}],
        "images": images,
        "annotations": annotations,
    }
    labels_path = split_directory / "labels.json"
    with labels_path.open("x", encoding="utf-8") as output:
        json.dump(labels, output, separators=(",", ":"), sort_keys=True)
        output.write("\n")
    return {
        "images": len(images),
        "annotations": len(annotations),
        "labels_json": str(labels_path),
        "labels_json_sha256": file_sha256(labels_path),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("records_jsonl")
    parser.add_argument("freeze_manifest")
    parser.add_argument("--output-directory", required=True)
    arguments = parser.parse_args()
    records_path = Path(arguments.records_jsonl).resolve()
    freeze_path = Path(arguments.freeze_manifest).resolve()
    output_directory = Path(arguments.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=False)
    with records_path.open("r", encoding="utf-8") as source:
        records = [json.loads(line) for line in source]
    with freeze_path.open("r", encoding="utf-8") as source:
        freeze = json.load(source)
    records_hash = file_sha256(records_path)
    if records_hash != freeze["records_jsonl_sha256"]:
        raise ValueError("records manifest does not match freeze SHA-256")
    split_results = {
        split: build_split(records, split, output_directory)
        for split in ("train", "valid", "test")
    }
    summary = {
        "schema_version": 1,
        "dataset_id": freeze["dataset_id"],
        "source_records_jsonl": str(records_path),
        "source_records_jsonl_sha256": records_hash,
        "freeze_manifest": str(freeze_path),
        "freeze_manifest_sha256": file_sha256(freeze_path),
        "split_results": split_results,
    }
    summary_path = output_directory / "coco_export_summary.json"
    with summary_path.open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
