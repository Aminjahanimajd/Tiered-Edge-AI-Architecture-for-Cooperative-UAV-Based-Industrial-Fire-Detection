#!/usr/bin/env python3
"""Create a derived manifest with adjudicated noisy source families removed."""

import argparse
import collections
import hashlib
import json
from pathlib import Path

try:
    from build_fire_manifest import validate
except ImportError:
    from tools.build_fire_manifest import validate


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def quarantine(records, source_families):
    source_families = set(source_families)
    removed = [
        record for record in records
        if record.get("source_family_group_id") in source_families
    ]
    retained = [
        record for record in records
        if record.get("source_family_group_id") not in source_families
    ]
    return retained, removed


def statistics(records):
    splits = {}
    for split in ("train", "valid", "test"):
        selected = [record for record in records if record["split"] == split]
        splits[split] = {
            "total": len(selected),
            "positive": sum(record["category"] == "fire_positive" for record in selected),
            "background": sum(record["category"] == "background" for record in selected),
        }
    return {
        "record_count": len(records),
        "box_count": sum(len(record.get("derived_label_rows", [])) for record in records),
        "group_count": len({record["group_id"] for record in records}),
        "split_counts": splits,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("records_jsonl")
    parser.add_argument("quarantine_manifest")
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--dataset-id", required=True)
    arguments = parser.parse_args()

    records_path = Path(arguments.records_jsonl).resolve()
    config_path = Path(arguments.quarantine_manifest).resolve()
    output_directory = Path(arguments.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=False)
    with records_path.open("r", encoding="utf-8") as source:
        records = [json.loads(line) for line in source]
    with config_path.open("r", encoding="utf-8") as source:
        config = json.load(source)
    expected_hash = config.get("source_records_jsonl_sha256")
    actual_hash = file_sha256(records_path)
    if expected_hash != actual_hash:
        raise ValueError("source records SHA-256 does not match quarantine manifest")
    families = config["excluded_source_family_group_ids"]
    if len(families) != len(set(families)):
        raise ValueError("duplicate source-family identifier")
    retained, removed = quarantine(records, families)
    found = {record.get("source_family_group_id") for record in removed}
    missing = sorted(set(families) - found)
    if missing:
        raise ValueError("quarantine family absent from source manifest: {}".format(missing))
    validate(retained)
    retained.sort(key=lambda item: (item["split"], item["group_id"], item["record_id"]))
    output_records = output_directory / "records.jsonl"
    with output_records.open("x", encoding="utf-8") as output:
        for record in retained:
            output.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    removed_by_family = collections.Counter(
        record["source_family_group_id"] for record in removed
    )
    summary = {
        "schema_version": 1,
        "dataset_id": arguments.dataset_id,
        "source_records_jsonl": str(records_path),
        "source_records_jsonl_sha256": actual_hash,
        "quarantine_manifest": str(config_path),
        "quarantine_manifest_sha256": file_sha256(config_path),
        "excluded_source_family_group_ids": sorted(families),
        "removed_records_by_source_family": dict(sorted(removed_by_family.items())),
        "removed_record_count": len(removed),
        "statistics": statistics(retained),
        "records_jsonl": str(output_records),
        "records_jsonl_sha256": file_sha256(output_records),
        "known_limitations": config.get("known_limitations", []),
    }
    with (output_directory / "summary.json").open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
