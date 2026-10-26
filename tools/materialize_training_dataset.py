#!/usr/bin/env python3
"""Materialize an immutable manifest as a standalone YOLO training tree."""

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path


SPLIT_DIRECTORY = {"train": "train", "valid": "valid", "test": "test"}


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def materialized_name(record):
    digest = hashlib.sha256(record["record_id"].encode("utf-8")).hexdigest()[:24]
    suffix = Path(record["image_path"]).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
        raise ValueError("unsupported image suffix: {}".format(suffix))
    return digest + suffix


def validate_freeze(records_path, freeze):
    actual_hash = file_sha256(records_path)
    if freeze["records_jsonl_sha256"] != actual_hash:
        raise ValueError("records manifest does not match freeze SHA-256")
    return actual_hash


def materialize(records, output_directory):
    rows = []
    names = set()
    for record in records:
        if record["split"] not in SPLIT_DIRECTORY:
            raise ValueError("unsupported split: {}".format(record["split"]))
        name = materialized_name(record)
        if name in names:
            raise ValueError("materialized filename collision: {}".format(name))
        names.add(name)
        split = SPLIT_DIRECTORY[record["split"]]
        image_directory = output_directory / "images" / split
        label_directory = output_directory / "labels" / split
        image_directory.mkdir(parents=True, exist_ok=True)
        label_directory.mkdir(parents=True, exist_ok=True)
        source_image = Path(record["image_path"])
        if not source_image.is_file():
            raise ValueError("source image is missing: {}".format(source_image))
        destination_image = image_directory / name
        destination_label = label_directory / (Path(name).stem + ".txt")
        shutil.copy2(str(source_image), str(destination_image))
        label_rows = record.get("derived_label_rows", [])
        destination_label.write_text(
            "".join(row.rstrip() + "\n" for row in label_rows), encoding="utf-8"
        )
        source_hash = file_sha256(source_image)
        destination_hash = file_sha256(destination_image)
        if source_hash != destination_hash:
            raise ValueError("copied image hash mismatch: {}".format(record["record_id"]))
        rows.append(
            {
                "materialized_name": name,
                "split": record["split"],
                "category": record["category"],
                "box_count": len(label_rows),
                "record_id": record["record_id"],
                "source_image": str(source_image),
                "image_sha256": source_hash,
            }
        )
    return rows


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
    records_hash = validate_freeze(records_path, freeze)
    if len(records) != freeze["record_count"]:
        raise ValueError("record count does not match freeze manifest")
    rows = materialize(records, output_directory)
    index_path = output_directory / "materialized_index.csv"
    fields = [
        "materialized_name", "split", "category", "box_count", "record_id",
        "source_image", "image_sha256"
    ]
    with index_path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    yaml_path = output_directory / "dataset.yaml"
    yaml_path.write_text(
        "path: {}\ntrain: images/train\nval: images/valid\ntest: images/test\nnames:\n  0: fire\n".format(
            output_directory.as_posix()
        ),
        encoding="utf-8",
    )
    summary = {
        "schema_version": 1,
        "dataset_id": freeze["dataset_id"],
        "source_records_jsonl": str(records_path),
        "source_records_jsonl_sha256": records_hash,
        "freeze_manifest": str(freeze_path),
        "freeze_manifest_sha256": file_sha256(freeze_path),
        "materialization_mode": "independent_copy",
        "record_count": len(rows),
        "image_bytes": sum((output_directory / "images" / SPLIT_DIRECTORY[row["split"]] / row["materialized_name"]).stat().st_size for row in rows),
        "split_counts": {
            split: sum(row["split"] == split for row in rows)
            for split in SPLIT_DIRECTORY
        },
        "positive_count": sum(row["category"] == "fire_positive" for row in rows),
        "background_count": sum(row["category"] == "background" for row in rows),
        "box_count": sum(row["box_count"] for row in rows),
        "materialized_index": str(index_path),
        "materialized_index_sha256": file_sha256(index_path),
        "dataset_yaml": str(yaml_path),
        "dataset_yaml_sha256": file_sha256(yaml_path),
    }
    summary_path = output_directory / "materialization_summary.json"
    with summary_path.open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
