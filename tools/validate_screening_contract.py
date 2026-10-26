#!/usr/bin/env python3
"""Validate and hash the frozen six-model validation contract."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_file(repo: Path, value: str) -> dict:
    path = repo / value
    return {
        "path": value,
        "exists": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else None,
        "sha256": file_sha256(path) if path.is_file() else None,
    }


def checkpoint_files(repo: Path, value: str) -> list[dict]:
    prefix = repo / value
    return [
        resolve_file(repo, str(path.relative_to(repo)).replace("\\", "/"))
        for path in sorted(prefix.parent.glob(prefix.name + ".*"))
    ]


def source_record_summary(path: Path, coco_images: list[dict]) -> dict:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    validation_records = [record for record in records if record.get("split") == "valid"]
    record_to_group = {
        record["record_id"]: record["group_id"] for record in validation_records
    }
    coco_record_ids = [image.get("record_id") for image in coco_images]
    return {
        "record_count": len(validation_records),
        "source_group_count": len(set(record_to_group.values())),
        "duplicate_record_ids": len(validation_records) - len(record_to_group),
        "coco_records_missing_from_manifest": sum(
            record_id not in record_to_group for record_id in coco_record_ids
        ),
        "manifest_records_missing_from_coco": len(set(record_to_group) - set(coco_record_ids)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"refusing to overwrite {arguments.output}")
    repo = arguments.repository.resolve()
    contract_path = arguments.contract.resolve()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if not contract.get("test_split_locked"):
        raise ValueError("validation contract must keep the test split locked")

    validation = contract["validation"]
    annotation = repo / validation["annotations"]
    annotation_json = json.loads(annotation.read_text(encoding="utf-8"))
    observed_hash = file_sha256(annotation)
    source_records = repo / validation["source_records"]
    source_hash = file_sha256(source_records)
    source_summary = source_record_summary(source_records, annotation_json["images"])
    validation_checks = {
        "annotations_exists": annotation.is_file(),
        "images_directory_exists": (repo / validation["images"]).is_dir(),
        "image_count": len(annotation_json["images"]),
        "annotation_count": len(annotation_json["annotations"]),
        "annotations_sha256": observed_hash,
        "expected_hash_matches": observed_hash == validation["annotations_sha256"],
        "expected_counts_match": (
            len(annotation_json["images"]) == validation["expected_images"]
            and len(annotation_json["annotations"]) == validation["expected_annotations"]
        ),
        "source_records_exists": source_records.is_file(),
        "source_records_sha256": source_hash,
        "expected_source_records_hash_matches": source_hash == validation["source_records_sha256"],
        "source_record_count": source_summary["record_count"],
        "source_group_count": source_summary["source_group_count"],
        "expected_source_group_count_matches": (
            source_summary["source_group_count"] == validation["expected_source_groups"]
        ),
        "duplicate_source_record_ids": source_summary["duplicate_record_ids"],
        "coco_records_missing_from_manifest": source_summary["coco_records_missing_from_manifest"],
        "manifest_records_missing_from_coco": source_summary["manifest_records_missing_from_coco"],
    }
    models = []
    for model in contract["models"]:
        evidence = {"model_id": model["model_id"], "framework": model["framework"]}
        if "pipeline_config" in model:
            evidence["pipeline_config"] = resolve_file(repo, model["pipeline_config"])
        if "checkpoint_directory" in model:
            directory = repo / model["checkpoint_directory"]
            state_file = directory / "checkpoint"
            evidence["checkpoint_state"] = resolve_file(
                repo, str(state_file.relative_to(repo)).replace("\\", "/")
            )
        if "checkpoint" in model:
            checkpoint = repo / model["checkpoint"]
            if checkpoint.suffix == ".pt":
                evidence["checkpoint"] = resolve_file(repo, model["checkpoint"])
            else:
                evidence["checkpoint_files"] = checkpoint_files(repo, model["checkpoint"])
        if "export" in model:
            evidence["export"] = resolve_file(repo, model["export"])
        direct_files_ready = all(
            record.get("exists", bool(record))
            for key, record in evidence.items()
            if isinstance(record, dict) and key != "checkpoint_files"
        )
        prefix_files = evidence.get("checkpoint_files")
        prefix_ready = bool(prefix_files) and all(item["exists"] for item in prefix_files)
        if "checkpoint_files" not in evidence:
            prefix_ready = True
        evidence["ready_for_validation"] = direct_files_ready and prefix_ready
        models.append(evidence)

    result = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "contract_path": str(contract_path),
        "contract_sha256": file_sha256(contract_path),
        "test_split_locked": True,
        "validation": validation_checks,
        "models": models,
        "ready_model_count": sum(bool(item["ready_for_validation"]) for item in models),
        "status": "pass" if (
            validation_checks["annotations_exists"]
            and validation_checks["images_directory_exists"]
            and validation_checks["expected_hash_matches"]
            and validation_checks["expected_counts_match"]
            and validation_checks["source_records_exists"]
            and validation_checks["expected_source_records_hash_matches"]
            and validation_checks["expected_source_group_count_matches"]
            and validation_checks["duplicate_source_record_ids"] == 0
            and validation_checks["coco_records_missing_from_manifest"] == 0
            and validation_checks["manifest_records_missing_from_coco"] == 0
        ) else "fail",
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
