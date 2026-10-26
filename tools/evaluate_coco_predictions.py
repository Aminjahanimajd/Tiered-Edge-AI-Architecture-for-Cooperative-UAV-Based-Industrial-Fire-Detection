#!/usr/bin/env python3
"""Apply one common COCO and thresholded-F1 protocol to detector predictions."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


RELATIVE_AREA_BINS = (
    ("very_small_lt_1pct", 0.0, 0.01),
    ("small_1_to_lt_5pct", 0.01, 0.05),
    ("medium_5_to_lt_20pct", 0.05, 0.20),
    ("large_ge_20pct", 0.20, float("inf")),
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def intersection_over_union(first: list[float], second: list[float]) -> float:
    ax1, ay1, aw, ah = first
    bx1, by1, bw, bh = second
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(
        0.0, min(ay2, by2) - max(ay1, by1)
    )
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0.0 else 0.0


def validate_inputs(ground_truth: dict, predictions: list[dict]) -> None:
    images = {int(image["id"]): image for image in ground_truth["images"]}
    categories = {int(category["id"]) for category in ground_truth["categories"]}
    for index, prediction in enumerate(predictions):
        required = {"image_id", "category_id", "bbox", "score"}
        if not required.issubset(prediction):
            raise ValueError(f"prediction {index} lacks {sorted(required - set(prediction))}")
        image_id = int(prediction["image_id"])
        category_id = int(prediction["category_id"])
        bbox = [float(value) for value in prediction["bbox"]]
        score = float(prediction["score"])
        if image_id not in images or category_id not in categories:
            raise ValueError(f"prediction {index} references an unknown image/category")
        if len(bbox) != 4 or not all(math.isfinite(value) for value in bbox):
            raise ValueError(f"prediction {index} has an invalid bbox")
        if bbox[2] <= 0.0 or bbox[3] <= 0.0:
            raise ValueError(f"prediction {index} has a nonpositive bbox")
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError(f"prediction {index} has an invalid score")


def threshold_metrics(
    ground_truth: dict,
    predictions: list[dict],
    threshold: float,
    iou_threshold: float = 0.5,
) -> dict[str, float | int]:
    image_dimensions = {
        int(image["id"]): (float(image["width"]), float(image["height"]))
        for image in ground_truth["images"]
        if "width" in image and "height" in image
    }
    gt_by_key: dict[tuple[int, int], list[list[float]]] = defaultdict(list)
    gt_size_by_key: dict[tuple[int, int], list[str | None]] = defaultdict(list)
    for annotation in ground_truth["annotations"]:
        if int(annotation.get("iscrowd", 0)):
            continue
        image_id = int(annotation["image_id"])
        key = (image_id, int(annotation["category_id"]))
        bbox = [float(value) for value in annotation["bbox"]]
        gt_by_key[key].append(bbox)
        size_bin = None
        if image_id in image_dimensions:
            width, height = image_dimensions[image_id]
            fraction = bbox[2] * bbox[3] / (width * height)
            size_bin = next(
                name for name, lower, upper in RELATIVE_AREA_BINS if lower <= fraction < upper
            )
        gt_size_by_key[key].append(size_bin)

    predictions_by_key: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for prediction in predictions:
        if float(prediction["score"]) >= threshold:
            predictions_by_key[
                (int(prediction["image_id"]), int(prediction["category_id"]))
            ].append(prediction)

    true_positive = false_positive = false_negative = 0
    size_totals = Counter()
    size_matches = Counter()
    for key in set(gt_by_key) | set(predictions_by_key):
        boxes = gt_by_key.get(key, [])
        for size_bin in gt_size_by_key.get(key, []):
            if size_bin is not None:
                size_totals[size_bin] += 1
        matched: set[int] = set()
        ordered = sorted(
            predictions_by_key.get(key, []), key=lambda item: float(item["score"]), reverse=True
        )
        for prediction in ordered:
            overlaps = [
                intersection_over_union([float(v) for v in prediction["bbox"]], box)
                if index not in matched
                else -1.0
                for index, box in enumerate(boxes)
            ]
            best_index = max(range(len(overlaps)), key=overlaps.__getitem__) if overlaps else None
            if best_index is not None and overlaps[best_index] >= iou_threshold:
                matched.add(best_index)
                true_positive += 1
                size_bin = gt_size_by_key[key][best_index]
                if size_bin is not None:
                    size_matches[size_bin] += 1
            else:
                false_positive += 1
        false_negative += len(boxes) - len(matched)

    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0

    positive_images = {int(item["image_id"]) for item in ground_truth["annotations"]}
    background_images = {int(item["id"]) for item in ground_truth["images"]} - positive_images
    predicted_background_images = {
        int(item["image_id"])
        for item in predictions
        if float(item["score"]) >= threshold and int(item["image_id"]) in background_images
    }
    background_rate = (
        len(predicted_background_images) / len(background_images) if background_images else None
    )
    result = {
        "threshold": threshold,
        "iou_threshold": iou_threshold,
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "background_images": len(background_images),
        "background_images_with_prediction": len(predicted_background_images),
        "background_false_positive_image_rate": background_rate,
    }
    if size_totals:
        result["ground_truth_recall_by_relative_box_area"] = {
            name: {
                "ground_truth_boxes": size_totals[name],
                "matched_boxes": size_matches[name],
                "recall": size_matches[name] / size_totals[name] if size_totals[name] else None,
                "area_fraction_interval": [lower, None if math.isinf(upper) else upper],
            }
            for name, lower, upper in RELATIVE_AREA_BINS
        }
    return result


def select_threshold(ground_truth: dict, predictions: list[dict]) -> dict:
    candidates = [value / 100.0 for value in range(1, 100)]
    evaluated = [threshold_metrics(ground_truth, predictions, value) for value in candidates]
    return max(evaluated, key=lambda item: (item["f1"], item["recall"], -item["threshold"]))


def coco_metrics(annotation_path: Path, predictions: list[dict]) -> dict[str, float]:
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval

    with contextlib.redirect_stdout(io.StringIO()):
        coco_ground_truth = COCO(str(annotation_path))
        coco_predictions = coco_ground_truth.loadRes(predictions)
        evaluator = COCOeval(coco_ground_truth, coco_predictions, "bbox")
        evaluator.evaluate()
        evaluator.accumulate()
    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        evaluator.summarize()
    names = [
        "ap_50_95", "ap_50", "ap_75", "ap_small", "ap_medium", "ap_large",
        "ar_1", "ar_10", "ar_100", "ar_small", "ar_medium", "ar_large",
    ]
    return {name: float(value) for name, value in zip(names, evaluator.stats)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--split", choices=("validation", "test"), required=True)
    parser.add_argument("--threshold", type=float)
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite {args.output}")
    if args.split == "test" and args.threshold is None:
        raise ValueError("test evaluation requires the frozen validation threshold")
    if args.split == "validation" and args.threshold is not None:
        raise ValueError("validation threshold must be selected by the frozen rule")

    ground_truth = json.loads(args.annotations.read_text(encoding="utf-8"))
    predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
    if not isinstance(predictions, list):
        raise TypeError("COCO predictions must be a JSON list")
    validate_inputs(ground_truth, predictions)
    selected = (
        select_threshold(ground_truth, predictions)
        if args.split == "validation"
        else threshold_metrics(ground_truth, predictions, args.threshold)
    )
    result = {
        "schema_version": 1,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "access_class": "NO LAB",
        "model_id": args.model_id,
        "split": args.split,
        "selection_data": "validation only",
        "ground_truth_sha256": file_sha256(args.annotations),
        "predictions_sha256": file_sha256(args.predictions),
        "evaluator_sha256": file_sha256(Path(__file__)),
        "image_count": len(ground_truth["images"]),
        "ground_truth_box_count": len(ground_truth["annotations"]),
        "prediction_count_at_floor": len(predictions),
        "coco": coco_metrics(args.annotations, predictions),
        "thresholded_iou50": selected,
        "limitations": [
            "One controlled training seed is available.",
            "Confidence-threshold metrics are object-level greedy matches at IoU 0.50.",
            "COCO AP is the primary threshold-independent predictive metric.",
            "Relative-size recall bins are descriptive strata defined before test evaluation; they do not establish performance on lighter-sized flames.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
