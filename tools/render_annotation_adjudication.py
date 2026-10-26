#!/usr/bin/env python3
"""Render full-resolution indexed boxes for non-acceptable review decisions."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw

try:
    from audit_fire_annotations import load_records, parse_yolo_bbox
except ImportError:
    from tools.audit_fire_annotations import load_records, parse_yolo_bbox


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("records_jsonl")
    parser.add_argument("review_decisions_csv")
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--include-classification", action="append", default=["incorrect", "questionable"])
    arguments = parser.parse_args()
    records_path = Path(arguments.records_jsonl).resolve()
    decisions_path = Path(arguments.review_decisions_csv).resolve()
    output_directory = Path(arguments.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=False)
    records = {record["record_id"]: record for record in load_records(records_path)}
    included = set(arguments.include_classification)
    with decisions_path.open("r", encoding="utf-8", newline="") as source:
        decisions = [
            row for row in csv.DictReader(source)
            if row["manual_classification"] in included
        ]
    outputs = []
    for row in decisions:
        record = records[row["record_id"]]
        source_path = Path(record["image_path"])
        with Image.open(source_path) as source:
            image = source.convert("RGB")
        draw = ImageDraw.Draw(image)
        line_width = max(2, min(image.size) // 160)
        indexed_boxes = []
        for box_index, label_row in enumerate(record["derived_label_rows"], 1):
            class_id, (center_x, center_y, width, height) = parse_yolo_bbox(label_row)
            left = (center_x - width / 2.0) * image.width
            top = (center_y - height / 2.0) * image.height
            right = (center_x + width / 2.0) * image.width
            bottom = (center_y + height / 2.0) * image.height
            draw.rectangle((left, top, right, bottom), outline=(255, 0, 0), width=line_width)
            draw.text((max(0, left + line_width), max(0, top + line_width)), str(box_index), fill=(255, 255, 0), stroke_width=1, stroke_fill=(0, 0, 0))
            indexed_boxes.append({
                "box_index": box_index,
                "class_id": class_id,
                "source_row": label_row,
                "pixel_edges": [left, top, right, bottom],
            })
        output_path = output_directory / "review_{:03d}_{}.jpg".format(int(row["queue_index"]), row["manual_classification"])
        image.save(output_path, quality=95)
        outputs.append({
            "queue_index": int(row["queue_index"]),
            "manual_classification": row["manual_classification"],
            "record_id": record["record_id"],
            "source_image": str(source_path),
            "source_image_sha256": sha256(source_path),
            "rendered_image": str(output_path),
            "rendered_image_sha256": sha256(output_path),
            "image_width": image.width,
            "image_height": image.height,
            "boxes": indexed_boxes,
        })
    manifest = {
        "schema_version": 1,
        "records_jsonl": str(records_path),
        "records_jsonl_sha256": sha256(records_path),
        "review_decisions_csv": str(decisions_path),
        "review_decisions_csv_sha256": sha256(decisions_path),
        "included_classifications": sorted(included),
        "rendered_count": len(outputs),
        "pixel_content_persisted": True,
        "purpose": "full-resolution annotation adjudication only; derived renders do not replace source images",
        "outputs": outputs,
    }
    manifest_path = output_directory / "adjudication_manifest.json"
    with manifest_path.open("x", encoding="utf-8") as output:
        json.dump(manifest, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps({
        "rendered_count": len(outputs),
        "manifest": str(manifest_path),
        "manifest_sha256": sha256(manifest_path),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
