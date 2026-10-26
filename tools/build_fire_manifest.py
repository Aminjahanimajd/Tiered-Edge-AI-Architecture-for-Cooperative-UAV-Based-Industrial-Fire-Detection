#!/usr/bin/env python3
"""Build a non-destructive, grouped, fire-only dataset manifest."""

from __future__ import print_function

import argparse
import collections
import hashlib
import json
import os
from pathlib import Path

try:
    from analyze_source_groups import augmentation_source_id, conservative_group_id
except ImportError:
    from tools.analyze_source_groups import (
        augmentation_source_id,
        conservative_group_id,
    )


SPLIT_FRACTIONS = {"train": 0.70, "valid": 0.15, "test": 0.15}
BASE_PROVENANCE = {
    "dataset": "Drone-Fire-Smoke v1",
    "license": "CC BY 4.0",
    "url": "https://universe.roboflow.com/mohammadamins-workspace/drone-fire-smoke-o58av-nj8ag/dataset/1",
}
NEGATIVE_PROVENANCE = {
    "weapd_fogsmog": {
        "dataset": "Weather Image Recognition / WEAPD derivative",
        "license": "CC0 (Kaggle dataset page)",
        "url": "https://www.kaggle.com/datasets/jehanbhathena/weather-dataset",
        "original_doi": "https://doi.org/10.7910/DVN/M8JQCR",
    },
    "weapd_sandstorm": {
        "dataset": "Weather Image Recognition / WEAPD derivative",
        "license": "CC0 (Kaggle dataset page)",
        "url": "https://www.kaggle.com/datasets/jehanbhathena/weather-dataset",
        "original_doi": "https://doi.org/10.7910/DVN/M8JQCR",
    },
    "weather_classification_cloudy": {
        "dataset": "Weather Classification",
        "license": "CC0 (Kaggle dataset page)",
        "url": "https://www.kaggle.com/datasets/vijaygiitk/multiclass-weather-dataset",
    },
    "weather_classification_foggy": {
        "dataset": "Weather Classification",
        "license": "CC0 (Kaggle dataset page)",
        "url": "https://www.kaggle.com/datasets/vijaygiitk/multiclass-weather-dataset",
    },
    "weather_classification_shine": {
        "dataset": "Weather Classification",
        "license": "CC0 (Kaggle dataset page)",
        "url": "https://www.kaggle.com/datasets/vijaygiitk/multiclass-weather-dataset",
    },
    "weather_classification_sunrise": {
        "dataset": "Weather Classification",
        "license": "CC0 (Kaggle dataset page)",
        "url": "https://www.kaggle.com/datasets/vijaygiitk/multiclass-weather-dataset",
    },
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_fire_label(path):
    fire_rows = []
    other_classes = set()
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split()
            try:
                class_id = int(float(parts[0]))
            except (ValueError, IndexError):
                raise ValueError("malformed label {}:{}".format(path, line_number))
            if class_id == 0:
                fire_rows.append(" ".join(["0"] + parts[1:]))
            else:
                other_classes.add(class_id)
    return fire_rows, other_classes


def base_records(base_root):
    records = []
    excluded = collections.Counter()
    for original_split in ("train", "valid", "test"):
        image_directory = base_root / original_split / "images"
        label_directory = base_root / original_split / "labels"
        for image_path in sorted(image_directory.iterdir()):
            if not image_path.is_file() or image_path.suffix.lower() not in {
                ".jpg",
                ".jpeg",
                ".png",
                ".gif",
                ".bmp",
                ".webp",
            }:
                continue
            label_path = label_directory / (image_path.stem + ".txt")
            if not label_path.is_file():
                raise ValueError("base image lacks label: {}".format(image_path))
            fire_rows, other_classes = parse_fire_label(label_path)
            if not fire_rows and other_classes:
                excluded["smoke_or_other_only"] += 1
                continue
            category = "fire_positive" if fire_rows else "background"
            source_id = augmentation_source_id(image_path.name)
            records.append(
                {
                    "record_id": "base/{}/{}".format(original_split, image_path.name),
                    "image_path": str(image_path.resolve()),
                    "original_label_path": str(label_path.resolve()),
                    "derived_label_rows": fire_rows,
                    "category": category,
                    "group_id": "base/{}".format(conservative_group_id(source_id)),
                    "original_split": original_split,
                    "provenance": BASE_PROVENANCE,
                }
            )
    return records, excluded


def negative_records(sentinel_root, provenance_report, included_sources):
    records = []
    excluded = collections.Counter()
    seen_hashes = {}
    for item in provenance_report["records"]:
        if item["status"] != "matched":
            excluded[item["status"]] += 1
            continue
        source_name = item["source_dataset"]
        if source_name not in included_sources:
            excluded["source_not_approved/{}".format(source_name)] += 1
            continue
        if source_name not in NEGATIVE_PROVENANCE:
            raise ValueError("no provenance policy for {}".format(source_name))
        image_path = sentinel_root / item["split"] / "images" / item["filename"]
        image_hash = sha256(image_path)
        if image_hash in seen_hashes:
            excluded["exact_duplicate_negative"] += 1
            continue
        seen_hashes[image_hash] = str(image_path)
        records.append(
            {
                "record_id": "negative/{}/{}".format(item["split"], item["filename"]),
                "image_path": str(image_path.resolve()),
                "original_label_path": None,
                "derived_label_rows": [],
                "category": "background",
                "group_id": "negative/{}/{}".format(source_name, image_hash),
                "original_split": item["split"],
                "image_sha256": image_hash,
                "provenance": NEGATIVE_PROVENANCE[source_name],
                "negative_source_key": source_name,
            }
        )
    return records, excluded


def assign_groups(records, seed):
    groups = collections.defaultdict(list)
    for record in records:
        groups[record["group_id"]].append(record)
    total_by_metric = {
        "total": len(records),
        "positive": sum(record["category"] == "fire_positive" for record in records),
        "background": sum(record["category"] == "background" for record in records),
    }
    targets = {
        split: {
            metric: total * fraction for metric, total in total_by_metric.items()
        }
        for split, fraction in SPLIT_FRACTIONS.items()
    }
    current = {
        split: {metric: 0 for metric in total_by_metric} for split in SPLIT_FRACTIONS
    }

    def group_stats(group_records):
        return {
            "total": len(group_records),
            "positive": sum(
                record["category"] == "fire_positive" for record in group_records
            ),
            "background": sum(
                record["category"] == "background" for record in group_records
            ),
        }

    group_items = []
    for group_id, group_records in groups.items():
        tie_breaker = hashlib.sha256(
            (str(seed) + "\0" + group_id).encode("utf-8")
        ).hexdigest()
        stats = group_stats(group_records)
        group_items.append((group_id, group_records, stats, tie_breaker))
    group_items.sort(key=lambda item: (-item[2]["total"], item[3]))

    for group_id, group_records, stats, _ in group_items:
        scores = {}
        for candidate_split in SPLIT_FRACTIONS:
            score = 0.0
            for evaluated_split in SPLIT_FRACTIONS:
                for metric in total_by_metric:
                    target = max(targets[evaluated_split][metric], 1.0)
                    projected = current[evaluated_split][metric]
                    if evaluated_split == candidate_split:
                        projected += stats[metric]
                    normalized_error = (projected - target) / target
                    score += normalized_error ** 2
                    if projected > target:
                        score += 2.0 * normalized_error ** 2
            scores[candidate_split] = score
        selected = min(sorted(scores), key=lambda split: scores[split])
        for metric in total_by_metric:
            current[selected][metric] += stats[metric]
        for record in group_records:
            record["split"] = selected
    return current, targets, groups


def validate(records):
    seen_records = set()
    group_splits = collections.defaultdict(set)
    for record in records:
        if record["record_id"] in seen_records:
            raise ValueError("duplicate record_id: {}".format(record["record_id"]))
        seen_records.add(record["record_id"])
        group_splits[record["group_id"]].add(record["split"])
    leaking = {
        group: sorted(splits) for group, splits in group_splits.items() if len(splits) > 1
    }
    if leaking:
        raise ValueError("group leakage detected: {}".format(list(leaking.items())[:5]))
    split_counts = collections.Counter(record["split"] for record in records)
    missing_splits = sorted(set(SPLIT_FRACTIONS) - set(split_counts))
    if missing_splits:
        raise ValueError("empty target splits: {}".format(missing_splits))
    return len(group_splits)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--sentinel", required=True)
    parser.add_argument("--negative-provenance", required=True)
    parser.add_argument("--include-negative-source", action="append", required=True)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--output-directory", required=True)
    arguments = parser.parse_args()
    base_root = Path(arguments.base).resolve()
    sentinel_root = Path(arguments.sentinel).resolve()
    output_directory = Path(arguments.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=False)
    with open(arguments.negative_provenance, "r", encoding="utf-8") as source:
        provenance_report = json.load(source)

    records, base_excluded = base_records(base_root)
    negatives, negative_excluded = negative_records(
        sentinel_root,
        provenance_report,
        set(arguments.include_negative_source),
    )
    records.extend(negatives)
    actual, targets, groups = assign_groups(records, arguments.seed)
    group_count = validate(records)
    records.sort(key=lambda item: (item["split"], item["group_id"], item["record_id"]))

    records_path = output_directory / "records.jsonl"
    with records_path.open("x", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
            output.write("\n")
    records_hash = sha256(records_path)
    summary = {
        "schema_version": 1,
        "dataset_id": "fire_only_grouped_manifest_v1",
        "seed": arguments.seed,
        "class_names": ["fire"],
        "annotation_policy": {
            "class_0_fire": "retained and remapped to class 0",
            "smoke_only_images": "excluded",
            "mixed_fire_smoke_images": "fire annotations retained; smoke is a non-target visual element",
            "negative_images": "empty YOLO label",
            "non_fire_object_class": "not used",
        },
        "split_fractions_requested": SPLIT_FRACTIONS,
        "split_counts_actual": actual,
        "split_counts_targets": targets,
        "records": len(records),
        "groups": group_count,
        "base_exclusions": dict(sorted(base_excluded.items())),
        "negative_exclusions": dict(sorted(negative_excluded.items())),
        "included_negative_sources": sorted(set(arguments.include_negative_source)),
        "records_jsonl": str(records_path),
        "records_jsonl_sha256": records_hash,
        "known_limitations": [
            "Filename-derived grouping cannot prove scene independence for every source.",
            "Exact and perceptual duplicate analysis across all base images is still required.",
            "A manual review of the largest conservative groups is required before training.",
            "This manifest is provisional until those checks are complete.",
        ],
    }
    with (output_directory / "summary.json").open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
