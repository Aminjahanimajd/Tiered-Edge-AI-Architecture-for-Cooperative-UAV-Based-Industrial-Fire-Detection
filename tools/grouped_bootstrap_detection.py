#!/usr/bin/env python3
"""Grouped bootstrap intervals for thresholded object-detection metrics."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

try:
    from evaluate_coco_predictions import threshold_metrics
    from summarize_latency import percentile
except ImportError:
    from tools.evaluate_coco_predictions import threshold_metrics
    from tools.summarize_latency import percentile


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def metric_values(counts: dict[str, int]) -> dict[str, float | None]:
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    background_rate = (
        counts["background_images_with_prediction"] / counts["background_images"]
        if counts["background_images"]
        else None
    )
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "background_false_positive_image_rate": background_rate,
    }


def add_counts(target: dict[str, int], source: dict) -> None:
    for key in ("tp", "fp", "fn", "background_images", "background_images_with_prediction"):
        target[key] += int(source[key])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--records-jsonl", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation", "test"), required=True)
    parser.add_argument("--threshold", type=float, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--resamples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"refusing to overwrite {arguments.output}")
    if arguments.resamples < 100:
        raise ValueError("at least 100 resamples are required")

    ground_truth = json.loads(arguments.annotations.read_text(encoding="utf-8"))
    predictions = json.loads(arguments.predictions.read_text(encoding="utf-8"))
    requested_record_split = "valid" if arguments.split == "validation" else arguments.split
    group_by_record = {}
    with arguments.records_jsonl.open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if record["split"] == requested_record_split:
                group_by_record[record["record_id"]] = record["group_id"]

    annotations_by_image = defaultdict(list)
    for annotation in ground_truth["annotations"]:
        annotations_by_image[int(annotation["image_id"])].append(annotation)
    predictions_by_image = defaultdict(list)
    for prediction in predictions:
        predictions_by_image[int(prediction["image_id"])].append(prediction)

    blank = lambda: {
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "background_images": 0,
        "background_images_with_prediction": 0,
    }
    counts_by_group = defaultdict(blank)
    missing_records = []
    for image in ground_truth["images"]:
        record_id = image.get("record_id")
        if record_id not in group_by_record:
            missing_records.append(record_id)
            continue
        image_id = int(image["id"])
        subset = {
            "images": [image],
            "categories": ground_truth["categories"],
            "annotations": annotations_by_image.get(image_id, []),
        }
        metrics = threshold_metrics(
            subset, predictions_by_image.get(image_id, []), arguments.threshold
        )
        add_counts(counts_by_group[group_by_record[record_id]], metrics)
    if missing_records:
        raise ValueError(f"{len(missing_records)} COCO records lack a source group")

    group_ids = sorted(counts_by_group)
    if len(group_ids) < 2:
        raise ValueError("grouped bootstrap requires at least two groups")
    total = blank()
    for counts in counts_by_group.values():
        add_counts(total, counts)
    point = metric_values(total)

    rng = random.Random(arguments.seed)
    distributions = {key: [] for key in point}
    for _ in range(arguments.resamples):
        sampled = blank()
        for _ in group_ids:
            add_counts(sampled, counts_by_group[rng.choice(group_ids)])
        values = metric_values(sampled)
        for key, value in values.items():
            if value is not None:
                distributions[key].append(value)
    intervals = {
        key: {
            "point_estimate": point[key],
            "lower_95_percentile": percentile(values, 0.025) if values else None,
            "upper_95_percentile": percentile(values, 0.975) if values else None,
            "valid_resamples": len(values),
        }
        for key, values in distributions.items()
    }
    result = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model_id": arguments.model_id,
        "split": arguments.split,
        "threshold": arguments.threshold,
        "group_count": len(group_ids),
        "image_count": len(ground_truth["images"]),
        "resamples": arguments.resamples,
        "seed": arguments.seed,
        "interval_method": "grouped nonparametric percentile bootstrap",
        "point_counts": total,
        "intervals": intervals,
        "annotations_sha256": file_sha256(arguments.annotations),
        "predictions_sha256": file_sha256(arguments.predictions),
        "records_jsonl_sha256": file_sha256(arguments.records_jsonl),
        "tool_sha256": file_sha256(Path(__file__)),
        "limitations": [
            "Group identifiers were inferred because original capture-session identifiers were unavailable.",
            "Intervals quantify resampling variability within retained groups and do not correct source-domain bias or annotation error.",
            "The percentile interval is descriptive and no statistical-significance claim is made.",
        ],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
