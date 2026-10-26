#!/usr/bin/env python3
"""Freeze validation decisions before the one authorized test-set evaluation."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--test-annotations", type=Path, required=True)
    parser.add_argument("--test-images", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    if output.exists() or manifest_path.exists():
        raise FileExistsError("refusing to overwrite an existing selection freeze")
    comparison_path = args.comparison.resolve()
    contract_path = args.contract.resolve()
    test_annotations = args.test_annotations.resolve()
    test_images = args.test_images.resolve()
    comparison = load(comparison_path)
    contract = load(contract_path)
    if comparison.get("candidate_count") != 6 or not comparison.get("test_split_locked"):
        raise ValueError("six completed validation candidates with a locked test split are required")
    if not contract.get("test_split_locked"):
        raise ValueError("the source contract does not retain the test lock")
    image_count = sum(1 for path in test_images.iterdir() if path.is_file())
    if image_count != 733:
        raise ValueError(f"expected 733 test images, observed {image_count}")

    rows = comparison["rows"]
    by_id = {row["model_id"]: row for row in rows}
    thresholds = {model_id: row["threshold"] for model_id, row in by_id.items()}
    evaluator_hashes = {
        json.loads(
            (comparison_path.parent.parent / "runs" / row["canonical_evidence_id"] / "metrics.json").read_text(
                encoding="utf-8"
            )
        )["evaluator_sha256"]
        for row in rows
    }
    if len(evaluator_hashes) != 1:
        raise ValueError("validation evaluator hashes differ across candidates")

    freeze = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "status": "frozen_before_test",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "author_role": "student principal engineer",
        "protocol_id": contract["protocol_id"],
        "contract_sha256": sha256(contract_path),
        "validation_comparison_sha256": sha256(comparison_path),
        "validation_annotations_sha256": contract["validation"]["annotations_sha256"],
        "candidate_count": len(rows),
        "validation_thresholds_iou50": thresholds,
        "threshold_policy": contract["threshold_policy"],
        "evaluator_sha256": next(iter(evaluator_hashes)),
        "canonical_evidence_ids": {
            row["model_id"]: row["canonical_evidence_id"] for row in rows
        },
        "exploratory_ap_latency_pareto_models": [
            row["model_id"] for row in rows if row["exploratory_ap_latency_pareto"]
        ],
        "validation_screening_outcome": {
            "highest_ap50_95": "yolov8n_416",
            "highest_recall_at_f1_threshold": ["yolov8n_416", "yolov8n_640"],
            "highest_precision_at_f1_threshold": "yolov8n_416",
            "sentinel_screening_candidate": "yolov8n_416",
            "scout_screening_candidate": "yolov8n_416",
            "interpretation": (
                "The post-hoc laptop screen does not support claiming that different model "
                "families are intrinsically optimal for the two roles. Hierarchical value must "
                "be evaluated from independent verification and deployment evidence."
            ),
        },
        "deployed_hardware_system_unchanged": {
            "sentinel": "final demonstrated YOLOv8n 640 TensorRT engine",
            "scout": "final demonstrated YOLOv8s 640 TFLite backend",
            "reason": (
                "The six-model screen is post-hoc laptop evidence and provides no new device "
                "deployment validation. It does not retroactively replace the hardware-tested pair."
            ),
        },
        "test_gate": {
            "state_at_freeze": "locked",
            "test_image_count": image_count,
            "test_annotations_sha256": sha256(test_annotations),
            "test_annotations_bytes": test_annotations.stat().st_size,
            "permitted_next_action": "one inference/evaluation pass for all six frozen candidates",
            "prohibited_after_opening": [
                "threshold tuning",
                "checkpoint selection",
                "model retraining based on test results",
                "silent evaluator changes",
            ],
        },
        "limitations": [
            "Only one controlled training seed is available per candidate.",
            "Laptop runtime paths differ by framework and accelerator; latency is pipeline-specific.",
            "The validation source groups are inferred because original session identities are incomplete.",
            "No six-candidate drone deployment comparison was performed.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "selection_freeze_path": str(output),
        "selection_freeze_bytes": output.stat().st_size,
        "selection_freeze_sha256": sha256(output),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
