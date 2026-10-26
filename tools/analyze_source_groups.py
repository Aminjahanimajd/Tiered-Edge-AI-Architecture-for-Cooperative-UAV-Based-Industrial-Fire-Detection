#!/usr/bin/env python3
"""Audit augmentation and sequence grouping without modifying a dataset."""

from __future__ import print_function

import argparse
import collections
import json
import os
import re
from pathlib import Path


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
ROBOFLOW_SUFFIX = re.compile(r"\.rf\.[0-9a-fA-F]{16,}$")
MOVIE_FRAME = re.compile(r"^(.*\.(?:mov|mp4|avi))[-_](?:frame[-_]?)?\d+(?:_(?:jpg|jpeg|png))?$", re.I)
NAMED_SEQUENCE = re.compile(
    r"^((?:youtube|video|vid|frame|image|img|fire|smoke)[-_A-Za-z]*)[-_]?\d+(?:_(?:jpg|jpeg|png))?$",
    re.I,
)
NUMERIC_FRAME = re.compile(r"^\d{4,}(?:_(?:jpg|jpeg|png))?$", re.I)


def augmentation_source_id(filename):
    stem = Path(filename).stem
    return ROBOFLOW_SUFFIX.sub("", stem)


def conservative_group_id(source_id):
    movie = MOVIE_FRAME.match(source_id)
    if movie:
        return "movie:" + movie.group(1).lower()
    named = NAMED_SEQUENCE.match(source_id)
    if named:
        return "named_sequence:" + named.group(1).lower().rstrip("-_")
    if NUMERIC_FRAME.match(source_id):
        return "unresolved_numeric_sequence"
    return "source:" + source_id.lower()


def label_classes(label_path):
    classes = set()
    if not label_path.is_file():
        return classes
    with label_path.open("r", encoding="utf-8") as source:
        for line in source:
            parts = line.split()
            if parts:
                try:
                    classes.add(int(float(parts[0])))
                except ValueError:
                    classes.add("MALFORMED")
    return classes


def overlap_report(group_splits):
    split_groups = collections.defaultdict(set)
    for group, splits in group_splits.items():
        for split in splits:
            split_groups[split].add(group)
    result = {}
    names = sorted(split_groups)
    for first_index, first in enumerate(names):
        for second in names[first_index + 1 :]:
            overlap = split_groups[first] & split_groups[second]
            result["{}<->{}".format(first, second)] = {
                "count": len(overlap),
                "examples": sorted(overlap)[:20],
            }
    return result


def analyze(dataset_root):
    dataset_root = Path(dataset_root).resolve()
    basic_groups = collections.defaultdict(set)
    conservative_groups = collections.defaultdict(set)
    group_members = collections.defaultdict(list)
    class_counts = collections.Counter()
    image_count = 0
    for split in ("train", "valid", "test"):
        image_directory = dataset_root / split / "images"
        label_directory = dataset_root / split / "labels"
        for image_path in sorted(image_directory.iterdir()):
            if image_path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            image_count += 1
            source_id = augmentation_source_id(image_path.name)
            group_id = conservative_group_id(source_id)
            basic_groups[source_id].add(split)
            conservative_groups[group_id].add(split)
            classes = label_classes(label_directory / (image_path.stem + ".txt"))
            if 0 in classes:
                category = "contains_fire"
            elif 1 in classes:
                category = "smoke_only"
            elif classes:
                category = "other_class_only"
            else:
                category = "background_or_missing_label"
            class_counts[category] += 1
            group_members[group_id].append(
                {
                    "split": split,
                    "filename": image_path.name,
                    "source_id": source_id,
                    "category": category,
                }
            )
    size_distribution = collections.Counter(len(items) for items in group_members.values())
    largest = sorted(
        (
            {
                "group_id": group,
                "images": len(items),
                "source_ids": len(set(item["source_id"] for item in items)),
                "splits": sorted(set(item["split"] for item in items)),
                "examples": [item["filename"] for item in items[:5]],
            }
            for group, items in group_members.items()
        ),
        key=lambda item: (-item["images"], item["group_id"]),
    )[:30]
    return {
        "schema_version": 1,
        "dataset_root": str(dataset_root),
        "image_count": image_count,
        "augmentation_source_groups": len(basic_groups),
        "conservative_groups": len(conservative_groups),
        "image_categories": dict(sorted(class_counts.items())),
        "basic_cross_split_overlap": overlap_report(basic_groups),
        "conservative_cross_split_overlap": overlap_report(conservative_groups),
        "conservative_group_size_distribution": {
            str(size): count for size, count in sorted(size_distribution.items())
        },
        "largest_conservative_groups": largest,
        "method_notes": [
            "Roboflow augmentation hashes are removed from the filename stem.",
            "Recognizable movie-frame and named-frame sequences are grouped conservatively.",
            "Pure numeric frame names are one unresolved conservative group because their source video is unknown.",
            "This filename analysis does not prove scene independence; manual provenance review remains required.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset_root")
    parser.add_argument("--output")
    arguments = parser.parse_args()
    report = analyze(arguments.dataset_root)
    payload = json.dumps(report, indent=2, sort_keys=True)
    if arguments.output:
        output_path = os.path.abspath(arguments.output)
        parent = os.path.dirname(output_path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        with open(output_path, "x", encoding="utf-8") as output:
            output.write(payload)
            output.write("\n")
    print(payload)


if __name__ == "__main__":
    main()
