#!/usr/bin/env python3
"""Audit fire-only YOLO annotations and create a deterministic visual queue."""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


def percentile(values, probability):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def numeric_summary(values):
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "minimum": min(values),
        "p01": percentile(values, 0.01),
        "p05": percentile(values, 0.05),
        "median": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "maximum": max(values),
        "mean": sum(values) / len(values),
    }


def parse_yolo_bbox(row):
    parts = row.split()
    if len(parts) != 5:
        raise ValueError("expected five YOLO fields, found {}".format(len(parts)))
    try:
        class_value = float(parts[0])
        coordinates = [float(value) for value in parts[1:]]
    except ValueError as error:
        raise ValueError("non-numeric YOLO field") from error
    if not all(math.isfinite(value) for value in [class_value] + coordinates):
        raise ValueError("non-finite YOLO field")
    if not class_value.is_integer():
        raise ValueError("class identifier is not an integer")
    return int(class_value), tuple(coordinates)


def size_stratum(minimum_normalized_area):
    if minimum_normalized_area is None:
        return "background"
    if minimum_normalized_area < 0.001:
        return "tiny_lt_0.001"
    if minimum_normalized_area < 0.01:
        return "small_0.001_to_0.01"
    if minimum_normalized_area < 0.10:
        return "medium_0.01_to_0.10"
    return "large_ge_0.10"


def stable_rank(record_id, seed):
    return hashlib.sha256((str(seed) + "\0" + record_id).encode("utf-8")).hexdigest()


def load_records(path):
    records = []
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError("invalid JSONL record {}".format(line_number)) from error
    return records


def audit_records(records):
    issue_counts = collections.Counter()
    issue_examples = collections.defaultdict(list)
    split_counts = collections.Counter()
    category_counts = collections.Counter()
    box_counts = []
    normalized_areas = []
    pixel_areas = []
    pixel_widths = []
    pixel_heights = []
    annotated_records = []

    def issue(name, record_id, detail=None):
        issue_counts[name] += 1
        if len(issue_examples[name]) < 20:
            example = {"record_id": record_id}
            if detail is not None:
                example["detail"] = detail
            issue_examples[name].append(example)

    for record in records:
        record_id = record.get("record_id", "[missing record_id]")
        split_counts[record.get("split", "[missing]")] += 1
        category_counts[record.get("category", "[missing]")] += 1
        image_path = Path(record.get("image_path", ""))
        rows = record.get("derived_label_rows")
        if not isinstance(rows, list):
            issue("derived_label_rows_not_list", record_id)
            rows = []
        if not image_path.is_file():
            issue("missing_image", record_id, str(image_path))
            continue
        original_label = record.get("original_label_path")
        if original_label is not None and not Path(original_label).is_file():
            issue("missing_original_label", record_id, original_label)
        category = record.get("category")
        if category == "fire_positive" and not rows:
            issue("positive_without_box", record_id)
        if category == "background" and rows:
            issue("background_with_box", record_id)
        duplicate_rows = len(rows) - len(set(rows))
        if duplicate_rows:
            issue("duplicate_label_rows", record_id, duplicate_rows)
        try:
            with Image.open(image_path) as image:
                image_width, image_height = image.size
                image.verify()
        except Exception as error:
            issue("unreadable_image", record_id, type(error).__name__)
            continue
        if image_width <= 0 or image_height <= 0:
            issue("invalid_image_dimensions", record_id)
            continue
        parsed_boxes = []
        for row_index, row in enumerate(rows, 1):
            try:
                class_id, (center_x, center_y, width, height) = parse_yolo_bbox(row)
            except ValueError as error:
                issue("malformed_yolo_row", record_id, "row {}: {}".format(row_index, error))
                continue
            if class_id != 0:
                issue("unexpected_class_id", record_id, class_id)
            if not (0.0 <= center_x <= 1.0 and 0.0 <= center_y <= 1.0):
                issue("center_out_of_range", record_id, row_index)
            if not (0.0 < width <= 1.0 and 0.0 < height <= 1.0):
                issue("size_out_of_range", record_id, row_index)
            left = center_x - width / 2.0
            right = center_x + width / 2.0
            top = center_y - height / 2.0
            bottom = center_y + height / 2.0
            if left < -1e-9 or top < -1e-9 or right > 1.0 + 1e-9 or bottom > 1.0 + 1e-9:
                issue("box_extends_outside_image", record_id, row_index)
            normalized_area = width * height
            pixel_width = width * image_width
            pixel_height = height * image_height
            pixel_area = pixel_width * pixel_height
            normalized_areas.append(normalized_area)
            pixel_widths.append(pixel_width)
            pixel_heights.append(pixel_height)
            pixel_areas.append(pixel_area)
            parsed_boxes.append((center_x, center_y, width, height))
        box_counts.append(len(parsed_boxes))
        minimum_area = min((box[2] * box[3] for box in parsed_boxes), default=None)
        annotated_records.append(
            {
                "record": record,
                "image_width": image_width,
                "image_height": image_height,
                "boxes": parsed_boxes,
                "minimum_normalized_area": minimum_area,
                "maximum_normalized_area": max(
                    (box[2] * box[3] for box in parsed_boxes), default=None
                ),
                "stratum": size_stratum(minimum_area),
            }
        )
    return {
        "record_count": len(records),
        "split_counts": dict(sorted(split_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
        "issue_examples": dict(sorted(issue_examples.items())),
        "box_count_per_record": numeric_summary(box_counts),
        "normalized_box_area": numeric_summary(normalized_areas),
        "pixel_box_area": numeric_summary(pixel_areas),
        "pixel_box_width": numeric_summary(pixel_widths),
        "pixel_box_height": numeric_summary(pixel_heights),
        "boxes_below_pixel_area": {
            "16": sum(value < 16 for value in pixel_areas),
            "64": sum(value < 64 for value in pixel_areas),
            "256": sum(value < 256 for value in pixel_areas),
            "1024": sum(value < 1024 for value in pixel_areas),
        },
        "box_count": len(normalized_areas),
        "annotated_records": annotated_records,
    }


def select_review_queue(annotated_records, seed, samples_per_stratum):
    strata = collections.defaultdict(list)
    for item in annotated_records:
        record = item["record"]
        key = (record.get("split", "[missing]"), item["stratum"])
        strata[key].append(item)
    selected = []
    for key in sorted(strata):
        ranked = sorted(
            strata[key], key=lambda item: stable_rank(item["record"]["record_id"], seed)
        )
        selected.extend(ranked[:samples_per_stratum])
    selected.sort(key=lambda item: (item["record"].get("split"), item["stratum"], item["record"]["record_id"]))
    return selected


def render_contact_sheets(selected, output_directory, items_per_page=8):
    output_directory.mkdir(parents=True, exist_ok=False)
    page_paths = []
    cell_width, cell_height = 420, 310
    for page_start in range(0, len(selected), items_per_page):
        page_items = selected[page_start : page_start + items_per_page]
        sheet = Image.new("RGB", (cell_width * 2, cell_height * 4), "white")
        draw = ImageDraw.Draw(sheet)
        for offset, item in enumerate(page_items):
            index = page_start + offset + 1
            column, row = offset % 2, offset // 2
            origin_x, origin_y = column * cell_width, row * cell_height
            record = item["record"]
            with Image.open(record["image_path"]) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((400, 250))
            image_draw = ImageDraw.Draw(image)
            for center_x, center_y, width, height in item["boxes"]:
                left = (center_x - width / 2.0) * image.width
                top = (center_y - height / 2.0) * image.height
                right = (center_x + width / 2.0) * image.width
                bottom = (center_y + height / 2.0) * image.height
                image_draw.rectangle((left, top, right, bottom), outline=(255, 0, 0), width=3)
            sheet.paste(image, (origin_x + 10, origin_y + 30))
            draw.text((origin_x + 10, origin_y + 8), "#{:03d} {} {} boxes={}".format(index, record.get("split"), item["stratum"], len(item["boxes"])), fill="black")
            draw.text((origin_x + 10, origin_y + 284), record["record_id"][:64], fill="black")
        page_number = len(page_paths) + 1
        page_path = output_directory / "annotation_review_page_{:03d}.jpg".format(page_number)
        sheet.save(page_path, quality=92)
        page_paths.append(str(page_path.resolve()))
    return page_paths


def write_review_csv(selected, output_path):
    with output_path.open("x", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "queue_index", "split", "stratum", "record_id", "image_path",
                "box_count", "minimum_normalized_area", "maximum_normalized_area",
                "manual_classification", "notes",
            ],
        )
        writer.writeheader()
        for index, item in enumerate(selected, 1):
            record = item["record"]
            writer.writerow(
                {
                    "queue_index": index,
                    "split": record.get("split"),
                    "stratum": item["stratum"],
                    "record_id": record["record_id"],
                    "image_path": record["image_path"],
                    "box_count": len(item["boxes"]),
                    "minimum_normalized_area": item["minimum_normalized_area"],
                    "maximum_normalized_area": item["maximum_normalized_area"],
                    "manual_classification": "",
                    "notes": "",
                }
            )


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("records_jsonl")
    parser.add_argument("--output", required=True)
    parser.add_argument("--review-csv", required=True)
    parser.add_argument("--contact-sheet-directory", required=True)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--samples-per-stratum", type=int, default=3)
    arguments = parser.parse_args()
    records_path = Path(arguments.records_jsonl).resolve()
    output_path = Path(arguments.output).resolve()
    review_path = Path(arguments.review_csv).resolve()
    records = load_records(records_path)
    audit = audit_records(records)
    annotated_records = audit.pop("annotated_records")
    selected = select_review_queue(annotated_records, arguments.seed, arguments.samples_per_stratum)
    write_review_csv(selected, review_path)
    page_paths = render_contact_sheets(selected, Path(arguments.contact_sheet_directory).resolve())
    report = {
        "schema_version": 1,
        "records_jsonl": str(records_path),
        "records_jsonl_sha256": file_sha256(records_path),
        "seed": arguments.seed,
        "samples_per_split_size_stratum": arguments.samples_per_stratum,
        "review_queue_count": len(selected),
        "review_queue_csv": str(review_path),
        "review_queue_csv_sha256": file_sha256(review_path),
        "contact_sheets": page_paths,
        "interpretation": [
            "Automated geometry validation does not establish semantic label correctness.",
            "The visual queue is deterministic and stratified, not a simple random prevalence sample.",
            "Normalized area strata use the smallest box in each positive image; backgrounds form a separate stratum.",
        ],
        "audit": audit,
    }
    with output_path.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps({
        "record_count": audit["record_count"],
        "box_count": audit["box_count"],
        "issue_counts": audit["issue_counts"],
        "review_queue_count": len(selected),
        "review_queue_csv_sha256": report["review_queue_csv_sha256"],
        "contact_sheet_count": len(page_paths),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
