#!/usr/bin/env python3
"""Create a reproducible COCO split health and object-size summary."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def describe(values: list[float]) -> dict:
    ordered = sorted(values)
    if not ordered:
        return {"n": 0}
    return {
        "n": len(ordered),
        "min": min(ordered),
        "median": statistics.median(ordered),
        "mean": statistics.fmean(ordered),
        "max": max(ordered),
        "standard_deviation_sample": statistics.stdev(ordered) if len(ordered) > 1 else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"refusing to overwrite {arguments.output}")
    data = json.loads(arguments.annotations.read_text(encoding="utf-8"))
    images = {int(item["id"]): item for item in data["images"]}
    annotated_images = {int(item["image_id"]) for item in data["annotations"]}
    counts = Counter(int(item["image_id"]) for item in data["annotations"])
    areas = [float(item["bbox"][2]) * float(item["bbox"][3]) for item in data["annotations"]]
    area_fractions = [
        area / (float(images[int(item["image_id"])]["width"]) * float(images[int(item["image_id"])]["height"]))
        for area, item in zip(areas, data["annotations"])
    ]
    size_counts = {
        "small_lt_32_squared_pixels": sum(area < 32**2 for area in areas),
        "medium_32_squared_to_96_squared_pixels": sum(32**2 <= area < 96**2 for area in areas),
        "large_ge_96_squared_pixels": sum(area >= 96**2 for area in areas),
    }
    result = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "split": arguments.split,
        "annotations_path": str(arguments.annotations.resolve()),
        "annotations_sha256": file_sha256(arguments.annotations),
        "image_count": len(images),
        "positive_image_count": len(annotated_images),
        "background_image_count": len(images) - len(annotated_images),
        "positive_image_fraction": len(annotated_images) / len(images),
        "annotation_count": len(data["annotations"]),
        "boxes_per_positive_image": describe([float(counts[item]) for item in annotated_images]),
        "box_area_pixels_squared": describe(areas),
        "box_area_fraction_of_image": describe(area_fractions),
        "coco_object_size_counts": size_counts,
        "coco_object_size_fractions": {
            key: value / len(areas) if areas else None for key, value in size_counts.items()
        },
        "definitions": {
            "background_image": "image with no retained target annotation",
            "positive_image": "image with at least one retained target annotation",
            "small_medium_large": "COCO pixel-area boundaries: <32^2, 32^2 to <96^2, and >=96^2",
        },
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
