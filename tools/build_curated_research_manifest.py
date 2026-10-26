#!/usr/bin/env python3
"""Build a smaller source-capped research manifest without copying data."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

try:
    from audit_fire_annotations import load_records
    from build_fire_manifest import assign_groups, validate
except ImportError:
    from tools.audit_fire_annotations import load_records
    from tools.build_fire_manifest import assign_groups, validate


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def curate_records(records, excluded_groups, maximum_records_per_group, seed):
    groups = collections.defaultdict(list)
    excluded = []
    for record in records:
        if record["group_id"] in excluded_groups:
            excluded.append(record)
        else:
            groups[record["group_id"]].append(record)
    missing_groups = sorted(set(excluded_groups) - {record["group_id"] for record in excluded})
    if missing_groups:
        raise ValueError("configured excluded groups absent from source: {}".format(missing_groups))
    selected = []
    capped_counts = {}
    for group_id in sorted(groups):
        members = groups[group_id]
        ranked = sorted(
            members,
            key=lambda record: hashlib.sha256(
                (str(seed) + "\0" + record["record_id"]).encode("utf-8")
            ).hexdigest(),
        )
        kept = ranked[:maximum_records_per_group]
        if len(members) > len(kept):
            capped_counts[group_id] = {"before": len(members), "after": len(kept)}
        for source_record in kept:
            record = dict(source_record)
            record["precuration_split"] = record["split"]
            record.pop("split", None)
            record["curation"] = {
                "source_manifest_version": 10,
                "selection_seed": seed,
                "maximum_records_per_group": maximum_records_per_group,
            }
            selected.append(record)
    return selected, excluded, capped_counts


def category_counts(records):
    counts = collections.Counter(record["category"] for record in records)
    return dict(sorted(counts.items()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("records_jsonl")
    parser.add_argument("curation_config")
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--dataset-id", required=True)
    arguments = parser.parse_args()
    source_path = Path(arguments.records_jsonl).resolve()
    config_path = Path(arguments.curation_config).resolve()
    output_directory = Path(arguments.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=False)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    source_records = load_records(source_path)
    selected, excluded, capped = curate_records(
        source_records,
        set(config["excluded_group_ids"]),
        int(config["maximum_records_per_group"]),
        int(config["seed"]),
    )
    selected_before_split = len(selected)
    actual, targets, _ = assign_groups(selected, int(config["seed"]))
    group_count = validate(selected)
    if selected_before_split != len(selected):
        raise AssertionError("split assignment changed record count")
    selected.sort(key=lambda record: (record["split"], record["group_id"], record["record_id"]))
    records_output_path = output_directory / "records.jsonl"
    with records_output_path.open("x", encoding="utf-8") as output:
        for record in selected:
            output.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    summary = {
        "schema_version": 1,
        "dataset_id": arguments.dataset_id,
        "source_records_jsonl": str(source_path),
        "source_records_jsonl_sha256": file_sha256(source_path),
        "curation_config": str(config_path),
        "curation_config_sha256": file_sha256(config_path),
        "records_jsonl": str(records_output_path),
        "records_jsonl_sha256": file_sha256(records_output_path),
        "source_record_count": len(source_records),
        "source_category_counts": category_counts(source_records),
        "excluded_record_count": len(excluded),
        "excluded_category_counts": category_counts(excluded),
        "excluded_group_counts": dict(sorted(collections.Counter(record["group_id"] for record in excluded).items())),
        "retained_before_cap_count": len(source_records) - len(excluded),
        "selected_record_count": len(selected),
        "selected_category_counts": category_counts(selected),
        "group_count": group_count,
        "capped_group_count": len(capped),
        "capped_groups": dict(sorted(capped.items())),
        "split_counts_actual": actual,
        "split_counts_targets": targets,
        "selection_policy": config["retention_policy"],
        "exclusion_rationale": config["exclusion_rationale"],
        "known_limitations": config["known_limitations"],
    }
    summary_path = output_directory / "summary.json"
    with summary_path.open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
