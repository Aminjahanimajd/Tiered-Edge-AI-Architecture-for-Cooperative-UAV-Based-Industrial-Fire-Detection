#!/usr/bin/env python3
"""Rank cross-split dHash candidates with stronger, continuous image metrics.

The resulting score is a review-prioritization heuristic.  It is not an
automatic duplicate label and must not be interpreted as ground truth.
"""

from __future__ import print_function

import argparse
import collections
import csv
import functools
import hashlib
import json
import math
import statistics
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps


METRIC_NAMES = (
    "rgb_mae",
    "gray_rmse",
    "gradient_mae",
    "histogram_distance",
    "gray_ncc",
    "review_priority_score",
)


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values, percentage):
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * float(percentage) / 100.0
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def describe(values):
    values = [float(value) for value in values if value is not None]
    if not values:
        return None
    return {
        "n": len(values),
        "minimum": min(values),
        "p10": percentile(values, 10),
        "p25": percentile(values, 25),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "p75": percentile(values, 75),
        "p90": percentile(values, 90),
        "maximum": max(values),
        "population_standard_deviation": statistics.pstdev(values),
    }


def load_records(path):
    records = {}
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            record_id = record["record_id"]
            if record_id in records:
                raise ValueError("duplicate record_id: {}".format(record_id))
            records[record_id] = record
    return records


@functools.lru_cache(maxsize=256)
def standardized_rgb(path_string, size):
    path = Path(path_string)
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        original_size = image.size
        standardized = image.resize((size, size), Image.Resampling.LANCZOS)
        array = np.asarray(standardized, dtype=np.float32) / 255.0
    return array, original_size


def grayscale(rgb):
    return (
        0.299 * rgb[:, :, 0]
        + 0.587 * rgb[:, :, 1]
        + 0.114 * rgb[:, :, 2]
    )


def histogram_distance(first, second, bins=32):
    intersections = []
    for channel in range(3):
        first_histogram, _ = np.histogram(
            first[:, :, channel], bins=bins, range=(0.0, 1.0)
        )
        second_histogram, _ = np.histogram(
            second[:, :, channel], bins=bins, range=(0.0, 1.0)
        )
        denominator = float(first_histogram.sum())
        intersection = float(np.minimum(first_histogram, second_histogram).sum())
        intersections.append(intersection / denominator)
    return 1.0 - statistics.fmean(intersections)


def zero_mean_correlation(first, second):
    first_centered = first - float(first.mean())
    second_centered = second - float(second.mean())
    denominator = float(
        np.sqrt(np.sum(first_centered ** 2) * np.sum(second_centered ** 2))
    )
    if denominator <= 1e-12:
        return None
    return float(np.sum(first_centered * second_centered) / denominator)


def orientation_metrics(first, second):
    first_gray = grayscale(first)
    second_gray = grayscale(second)
    rgb_mae = float(np.mean(np.abs(first - second)))
    gray_rmse = float(np.sqrt(np.mean((first_gray - second_gray) ** 2)))
    horizontal_error = np.mean(
        np.abs(np.diff(first_gray, axis=1) - np.diff(second_gray, axis=1))
    )
    vertical_error = np.mean(
        np.abs(np.diff(first_gray, axis=0) - np.diff(second_gray, axis=0))
    )
    gradient_mae = float((horizontal_error + vertical_error) / 2.0)
    color_histogram_distance = histogram_distance(first, second)
    ncc = zero_mean_correlation(first_gray, second_gray)
    review_priority_score = 1.0 - (
        0.40 * rgb_mae
        + 0.25 * gray_rmse
        + 0.20 * gradient_mae
        + 0.15 * color_histogram_distance
    )
    return {
        "rgb_mae": rgb_mae,
        "gray_rmse": gray_rmse,
        "gradient_mae": gradient_mae,
        "histogram_distance": color_histogram_distance,
        "gray_ncc": ncc,
        "review_priority_score": max(0.0, min(1.0, review_priority_score)),
        "normalized_pixel_identical": bool(np.array_equal(first, second)),
    }


def compare_arrays(first, second):
    direct = orientation_metrics(first, second)
    mirrored = orientation_metrics(first, np.flip(second, axis=1))
    if mirrored["review_priority_score"] > direct["review_priority_score"]:
        selected = dict(mirrored)
        selected["orientation"] = "second_mirrored"
    else:
        selected = dict(direct)
        selected["orientation"] = "direct"
    return selected


def split_route(first, second):
    return "--".join(sorted((first["split"], second["split"])))


def category_pair(first, second):
    return "--".join(sorted((first["category"], second["category"])))


def analyze_pairs(records, candidate_report, size):
    if candidate_report.get("near_pair_examples_truncated"):
        raise ValueError("candidate report is truncated; regenerate all pairs first")
    expected = int(candidate_report["near_cross_split_pair_count"])
    candidates = [
        item for item in candidate_report["near_pair_examples"] if item["cross_split"]
    ]
    if len(candidates) != expected:
        raise ValueError(
            "cross-split candidate count mismatch: {} != {}".format(
                len(candidates), expected
            )
        )
    results = []
    for candidate in candidates:
        first = records[candidate["first_record_id"]]
        second = records[candidate["second_record_id"]]
        first_array, first_size = standardized_rgb(first["image_path"], size)
        second_array, second_size = standardized_rgb(second["image_path"], size)
        metrics = compare_arrays(first_array, second_array)
        result = {
            "first_record_id": first["record_id"],
            "second_record_id": second["record_id"],
            "first_group_id": first["group_id"],
            "second_group_id": second["group_id"],
            "first_split": first["split"],
            "second_split": second["split"],
            "split_route": split_route(first, second),
            "first_category": first["category"],
            "second_category": second["category"],
            "category_pair": category_pair(first, second),
            "first_original_size": list(first_size),
            "second_original_size": list(second_size),
            "dhash_distance": int(candidate["distance"]),
        }
        result.update(metrics)
        results.append(result)
    results.sort(
        key=lambda item: (
            -item["review_priority_score"],
            item["first_record_id"],
            item["second_record_id"],
        )
    )
    return results


def review_queue(results, top_count=60, quantiles=(0, 25, 50, 75, 100)):
    selected = {}
    for result in results[:top_count]:
        key = (result["first_record_id"], result["second_record_id"])
        selected[key] = dict(result, selection_reason="top_similarity")
    strata = collections.defaultdict(list)
    for result in results:
        strata[(result["dhash_distance"], result["category_pair"])].append(result)
    for stratum, items in sorted(strata.items()):
        items.sort(key=lambda item: item["review_priority_score"], reverse=True)
        for quantile in quantiles:
            index = int(round((len(items) - 1) * quantile / 100.0))
            item = items[index]
            key = (item["first_record_id"], item["second_record_id"])
            if key not in selected:
                selected[key] = dict(
                    item,
                    selection_reason="stratum_{}_{}_q{}".format(
                        stratum[0], stratum[1], quantile
                    ),
                )
    return sorted(
        selected.values(),
        key=lambda item: (
            -item["review_priority_score"],
            item["first_record_id"],
            item["second_record_id"],
        ),
    )


def save_contact_sheets(queue, records, output_directory, pairs_per_page=12):
    if output_directory.exists():
        raise FileExistsError("contact-sheet directory already exists: {}".format(output_directory))
    output_directory.mkdir(parents=True)
    page_width = 1000
    row_height = 210
    thumbnail_size = (280, 170)
    paths = []
    for offset in range(0, len(queue), pairs_per_page):
        page_items = queue[offset : offset + pairs_per_page]
        canvas = Image.new("RGB", (page_width, row_height * len(page_items)), "white")
        draw = ImageDraw.Draw(canvas)
        for row, item in enumerate(page_items):
            y = row * row_height
            for column, record_key in enumerate(("first_record_id", "second_record_id")):
                record = records[item[record_key]]
                with Image.open(record["image_path"]) as source:
                    image = ImageOps.exif_transpose(source).convert("RGB")
                    if column == 1 and item["orientation"] == "second_mirrored":
                        image = ImageOps.mirror(image)
                    image.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)
                    x = 5 + column * 290
                    canvas.paste(image, (x, y + 5))
            text = (
                "#{:03d} score={:.4f} dHash={} {}\n{}\n{}\n{}"
            ).format(
                offset + row + 1,
                item["review_priority_score"],
                item["dhash_distance"],
                item["orientation"],
                item["category_pair"],
                item["first_record_id"],
                item["second_record_id"],
            )
            draw.multiline_text((590, y + 10), text, fill="black", spacing=4)
        page_path = output_directory / "review_page_{:03d}.jpg".format(
            len(paths) + 1
        )
        canvas.save(page_path, quality=90)
        paths.append(page_path)
    return paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("records_jsonl")
    parser.add_argument("candidate_report")
    parser.add_argument("--output", required=True)
    parser.add_argument("--review-csv", required=True)
    parser.add_argument("--contact-sheet-directory")
    parser.add_argument("--standardized-size", type=int, default=128)
    parser.add_argument("--top-review-count", type=int, default=60)
    arguments = parser.parse_args()
    if arguments.standardized_size < 32:
        raise ValueError("--standardized-size must be at least 32")
    records_path = Path(arguments.records_jsonl).resolve()
    candidates_path = Path(arguments.candidate_report).resolve()
    output_path = Path(arguments.output).resolve()
    review_csv_path = Path(arguments.review_csv).resolve()
    for output in (output_path, review_csv_path):
        if output.exists():
            raise FileExistsError("output already exists: {}".format(output))
        output.parent.mkdir(parents=True, exist_ok=True)
    records = load_records(records_path)
    candidate_report = json.loads(candidates_path.read_text(encoding="utf-8"))
    results = analyze_pairs(records, candidate_report, arguments.standardized_size)
    queue = review_queue(results, arguments.top_review_count)
    counts = {
        "by_dhash_distance": dict(
            sorted(collections.Counter(item["dhash_distance"] for item in results).items())
        ),
        "by_category_pair": dict(
            sorted(collections.Counter(item["category_pair"] for item in results).items())
        ),
        "by_split_route": dict(
            sorted(collections.Counter(item["split_route"] for item in results).items())
        ),
        "selected_mirrored_orientation": sum(
            item["orientation"] == "second_mirrored" for item in results
        ),
        "normalized_pixel_identical": sum(
            item["normalized_pixel_identical"] for item in results
        ),
    }
    report = {
        "schema_version": 1,
        "records_jsonl": str(records_path),
        "records_jsonl_sha256": file_sha256(records_path),
        "candidate_report": str(candidates_path),
        "candidate_report_sha256": file_sha256(candidates_path),
        "standardization": {
            "size": [arguments.standardized_size, arguments.standardized_size],
            "color_space": "RGB normalized to [0,1]",
            "resize": "Pillow LANCZOS stretch; aspect ratios retained separately",
            "orientation": "select direct or horizontal mirror by priority score",
        },
        "metrics": {
            name: describe([item[name] for item in results]) for name in METRIC_NAMES
        },
        "counts": counts,
        "cross_split_pair_count": len(results),
        "manual_review_queue_count": len(queue),
        "review_priority_formula": (
            "1 - (0.40*rgb_mae + 0.25*gray_rmse + "
            "0.20*gradient_mae + 0.15*histogram_distance)"
        ),
        "interpretation": [
            "The score ranks manual review priority and is not a duplicate label.",
            "All metrics are descriptive; no statistical significance is claimed.",
            "Square stretching can hide or exaggerate geometric differences, so original dimensions are retained.",
            "Horizontal mirroring is evaluated because the upstream dHash screen was mirror-invariant.",
            "Manual review or stronger source-sequence evidence is required before changing a split.",
        ],
        "pairs": results,
    }
    with output_path.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")
    fieldnames = list(queue[0]) if queue else []
    with review_csv_path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(queue)
    contact_sheets = []
    if arguments.contact_sheet_directory:
        contact_sheets = save_contact_sheets(
            queue, records, Path(arguments.contact_sheet_directory).resolve()
        )
    print(
        json.dumps(
            {
                "cross_split_pair_count": len(results),
                "manual_review_queue_count": len(queue),
                "contact_sheet_count": len(contact_sheets),
                "counts": counts,
                "output_sha256": file_sha256(output_path),
                "review_csv_sha256": file_sha256(review_csv_path),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
