#!/usr/bin/env python3
"""Build a conservative source-family manifest and apply reviewed must-links."""

from __future__ import print_function

import argparse
import collections
import csv
import hashlib
import json
import re
from pathlib import Path

try:
    from analyze_source_groups import augmentation_source_id
    from build_fire_manifest import assign_groups, validate
    from regroup_manifest_from_review import (
        DisjointGroups,
        MERGE_LABELS,
        component_identifier,
    )
except ImportError:
    from tools.analyze_source_groups import augmentation_source_id
    from tools.build_fire_manifest import assign_groups, validate
    from tools.regroup_manifest_from_review import (
        DisjointGroups,
        MERGE_LABELS,
        component_identifier,
    )


DIGIT_RUN = re.compile(r"\d+")
IMG_CAPTURE = re.compile(r"^img(?:_|-)", re.I)


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_family_group_id(record):
    if not record["record_id"].startswith("base/"):
        return record["group_id"]
    filename = record["record_id"].split("/", 2)[2]
    source_id = augmentation_source_id(filename).lower()
    if IMG_CAPTURE.match(source_id):
        return "base/source_family:img_capture_collection"
    signature = DIGIT_RUN.sub("#", source_id)
    return "base/source_family:{}".format(signature)


def load_decisions(paths):
    decisions = []
    for path in paths:
        with path.open("r", encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source):
                row = dict(row)
                row["decision_source"] = str(path)
                decisions.append(row)
    return decisions


def apply_source_families(records, decisions):
    record_index = {record["record_id"]: record for record in records}
    if len(record_index) != len(records):
        raise ValueError("duplicate record_id in source manifest")
    for record in records:
        record["previous_group_id"] = record["group_id"]
        record["previous_split"] = record["split"]
        record["group_id"] = source_family_group_id(record)
        del record["split"]
    initial_groups = sorted({record["group_id"] for record in records})
    disjoint = DisjointGroups(initial_groups)
    used_edges = []
    for decision in decisions:
        if decision["visual_label"] not in MERGE_LABELS:
            continue
        try:
            first_group = record_index[decision["first_record_id"]]["group_id"]
            second_group = record_index[decision["second_record_id"]]["group_id"]
        except KeyError as exc:
            raise ValueError("review decision refers to an unknown record") from exc
        changed = disjoint.union(first_group, second_group)
        used_edges.append(
            {
                "decision_source": decision["decision_source"],
                "review_index": int(decision["review_index"]),
                "label": decision["visual_label"],
                "first_record_id": decision["first_record_id"],
                "second_record_id": decision["second_record_id"],
                "first_source_family": first_group,
                "second_source_family": second_group,
                "union_changed_component": changed,
            }
        )
    members_by_root = collections.defaultdict(list)
    for group in initial_groups:
        members_by_root[disjoint.find(group)].append(group)
    replacement = {}
    merged_components = []
    for members in members_by_root.values():
        identifier = component_identifier(members)
        for member in members:
            replacement[member] = identifier
        if len(members) > 1:
            merged_components.append(
                {"group_id": identifier, "member_source_families": sorted(members)}
            )
    for record in records:
        record["source_family_group_id"] = record["group_id"]
        record["group_id"] = replacement[record["group_id"]]
    return initial_groups, used_edges, merged_components


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("records_jsonl")
    parser.add_argument("--review-decisions", action="append", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--dataset-id", default="fire_only_source_family_manifest_v3")
    parser.add_argument("--seed", type=int, default=20260729)
    arguments = parser.parse_args()
    records_path = Path(arguments.records_jsonl).resolve()
    decision_paths = [Path(path).resolve() for path in arguments.review_decisions]
    output_directory = Path(arguments.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=False)
    with records_path.open("r", encoding="utf-8") as source:
        records = [json.loads(line) for line in source]
    original_record_ids = {record["record_id"] for record in records}
    decisions = load_decisions(decision_paths)
    initial_groups, used_edges, merged_components = apply_source_families(
        records, decisions
    )
    actual, targets, _ = assign_groups(records, arguments.seed)
    final_group_count = validate(records)
    if {record["record_id"] for record in records} != original_record_ids:
        raise ValueError("record identity changed during source-family grouping")
    records_changed_split = sum(
        record["split"] != record["previous_split"] for record in records
    )
    records.sort(key=lambda item: (item["split"], item["group_id"], item["record_id"]))
    output_records = output_directory / "records.jsonl"
    with output_records.open("x", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
            output.write("\n")
    crosswalk_path = output_directory / "source_family_crosswalk.json"
    with crosswalk_path.open("x", encoding="utf-8") as output:
        json.dump(
            {
                "schema_version": 1,
                "img_rule": "all base source IDs beginning IMG_ or IMG- share one conservative family",
                "other_base_rule": "all digit runs in the augmentation-stripped source ID are replaced by #",
                "negative_rule": "retain v1 negative groups, then apply reviewed must-links",
                "merge_labels": sorted(MERGE_LABELS),
                "used_review_edges": used_edges,
                "merged_components": sorted(
                    merged_components, key=lambda item: item["group_id"]
                ),
            },
            output,
            indent=2,
            sort_keys=True,
        )
        output.write("\n")
    decision_inputs = [
        {"path": str(path), "sha256": file_sha256(path)} for path in decision_paths
    ]
    summary = {
        "schema_version": 1,
        "dataset_id": arguments.dataset_id,
        "seed": arguments.seed,
        "source_records_jsonl": str(records_path),
        "source_records_jsonl_sha256": file_sha256(records_path),
        "review_decision_inputs": decision_inputs,
        "records": len(records),
        "source_family_groups_before_reviewed_merges": len(initial_groups),
        "final_groups": final_group_count,
        "review_edges_used": len(used_edges),
        "review_edges_changing_components": sum(
            edge["union_changed_component"] for edge in used_edges
        ),
        "merged_component_count": len(merged_components),
        "records_changed_split_from_v1": records_changed_split,
        "split_fractions_requested": {"train": 0.70, "valid": 0.15, "test": 0.15},
        "split_counts_actual": actual,
        "split_counts_targets": targets,
        "records_jsonl": str(output_records),
        "records_jsonl_sha256": file_sha256(output_records),
        "source_family_crosswalk": str(crosswalk_path),
        "source_family_crosswalk_sha256": file_sha256(crosswalk_path),
        "known_limitations": [
            "Digit-normalized families are conservative filename evidence, not recovered original video IDs.",
            "The broad IMG capture family may contain independent scenes and reduces effective source diversity.",
            "Negative groups remain image-level except where reviewed must-link edges connect them.",
            "A complete repeated duplicate and visual audit is required before training.",
        ],
    }
    with (output_directory / "summary.json").open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
