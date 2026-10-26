#!/usr/bin/env python3
"""Create a new grouped manifest from reviewed must-link decisions."""

from __future__ import print_function

import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path

try:
    from build_fire_manifest import SPLIT_FRACTIONS, assign_groups, validate
except ImportError:
    from tools.build_fire_manifest import SPLIT_FRACTIONS, assign_groups, validate


MERGE_LABELS = {"visually_same_scene", "uncertain_related_sequence"}


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class DisjointGroups(object):
    def __init__(self, values):
        self.parent = {value: value for value in values}

    def find(self, value):
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, first, second):
        first_root = self.find(first)
        second_root = self.find(second)
        if first_root == second_root:
            return False
        canonical = min(first_root, second_root)
        other = max(first_root, second_root)
        self.parent[other] = canonical
        return True


def component_identifier(members):
    members = sorted(members)
    if len(members) == 1:
        return members[0]
    digest = hashlib.sha256("\n".join(members).encode("utf-8")).hexdigest()[:20]
    return "review_component:{}".format(digest)


def regroup(records, decisions):
    original_groups = sorted({record["group_id"] for record in records})
    disjoint = DisjointGroups(original_groups)
    used_edges = []
    for decision in decisions:
        if decision["visual_label"] not in MERGE_LABELS:
            continue
        first = decision["first_group_id"]
        second = decision["second_group_id"]
        if first not in disjoint.parent or second not in disjoint.parent:
            raise ValueError("review decision refers to an unknown group")
        changed = disjoint.union(first, second)
        used_edges.append(
            {
                "review_index": int(decision["review_index"]),
                "label": decision["visual_label"],
                "first_group_id": first,
                "second_group_id": second,
                "union_changed_component": changed,
            }
        )
    members_by_root = collections.defaultdict(list)
    for group in original_groups:
        members_by_root[disjoint.find(group)].append(group)
    replacement = {}
    merged_components = []
    for members in members_by_root.values():
        identifier = component_identifier(members)
        for member in members:
            replacement[member] = identifier
        if len(members) > 1:
            merged_components.append(
                {"group_id": identifier, "member_group_ids": sorted(members)}
            )
    for record in records:
        record["previous_group_id"] = record["group_id"]
        record["previous_split"] = record["split"]
        record["group_id"] = replacement[record["group_id"]]
        del record["split"]
    return used_edges, sorted(merged_components, key=lambda item: item["group_id"])


def assign_preserving_existing_splits(records):
    """Keep unaffected groups fixed and conservatively route merged components.

    Components that span splits are assigned to train when training data are
    involved, otherwise to validation before test.  This prevents a source seen
    during training from surviving in an evaluation split and avoids repeatedly
    reshuffling unrelated groups during iterative duplicate adjudication.
    """
    groups = collections.defaultdict(list)
    for record in records:
        groups[record["group_id"]].append(record)
    split_priority = {"train": 0, "valid": 1, "test": 2}
    for group_records in groups.values():
        previous_splits = {record["previous_split"] for record in group_records}
        unknown = previous_splits - set(split_priority)
        if unknown:
            raise ValueError("unknown previous split: {}".format(sorted(unknown)))
        selected = min(previous_splits, key=lambda split: split_priority[split])
        for record in group_records:
            record["split"] = selected

    totals = {
        "total": len(records),
        "positive": sum(record["category"] == "fire_positive" for record in records),
        "background": sum(record["category"] == "background" for record in records),
    }
    targets = {
        split: {metric: total * fraction for metric, total in totals.items()}
        for split, fraction in SPLIT_FRACTIONS.items()
    }
    actual = {
        split: {
            "total": sum(record["split"] == split for record in records),
            "positive": sum(
                record["split"] == split and record["category"] == "fire_positive"
                for record in records
            ),
            "background": sum(
                record["split"] == split and record["category"] == "background"
                for record in records
            ),
        }
        for split in SPLIT_FRACTIONS
    }
    return actual, targets, groups


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("records_jsonl")
    parser.add_argument("review_decisions_csv")
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--dataset-id", default="fire_only_grouped_manifest_v2")
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--preserve-existing-splits", action="store_true")
    arguments = parser.parse_args()
    records_path = Path(arguments.records_jsonl).resolve()
    decisions_path = Path(arguments.review_decisions_csv).resolve()
    output_directory = Path(arguments.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=False)
    with records_path.open("r", encoding="utf-8") as source:
        records = [json.loads(line) for line in source]
    with decisions_path.open("r", encoding="utf-8", newline="") as source:
        decisions = list(csv.DictReader(source))
    original_record_ids = {record["record_id"] for record in records}
    original_group_count = len({record["group_id"] for record in records})
    used_edges, merged_components = regroup(records, decisions)
    if arguments.preserve_existing_splits:
        actual, targets, _ = assign_preserving_existing_splits(records)
        split_assignment_method = "preserve_unaffected_train_preferred_for_merges"
    else:
        actual, targets, _ = assign_groups(records, arguments.seed)
        split_assignment_method = "full_deterministic_rebalance"
    group_count = validate(records)
    if {record["record_id"] for record in records} != original_record_ids:
        raise ValueError("record identity changed during regrouping")
    records_changed_split = sum(
        record["split"] != record["previous_split"] for record in records
    )
    records.sort(key=lambda item: (item["split"], item["group_id"], item["record_id"]))
    output_records = output_directory / "records.jsonl"
    with output_records.open("x", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
            output.write("\n")
    crosswalk_path = output_directory / "review_group_crosswalk.json"
    with crosswalk_path.open("x", encoding="utf-8") as output:
        json.dump(
            {
                "schema_version": 1,
                "merge_labels": sorted(MERGE_LABELS),
                "used_review_edges": used_edges,
                "merged_components": merged_components,
            },
            output,
            indent=2,
            sort_keys=True,
        )
        output.write("\n")
    summary = {
        "schema_version": 1,
        "dataset_id": arguments.dataset_id,
        "seed": arguments.seed,
        "source_records_jsonl": str(records_path),
        "source_records_jsonl_sha256": file_sha256(records_path),
        "review_decisions_csv": str(decisions_path),
        "review_decisions_csv_sha256": file_sha256(decisions_path),
        "records": len(records),
        "original_groups": original_group_count,
        "regrouped_groups": group_count,
        "review_edges_used": len(used_edges),
        "merged_component_count": len(merged_components),
        "records_changed_split": records_changed_split,
        "split_assignment_method": split_assignment_method,
        "split_fractions_requested": {"train": 0.70, "valid": 0.15, "test": 0.15},
        "split_counts_actual": actual,
        "split_counts_targets": targets,
        "records_jsonl": str(output_records),
        "records_jsonl_sha256": file_sha256(output_records),
        "review_group_crosswalk": str(crosswalk_path),
        "review_group_crosswalk_sha256": file_sha256(crosswalk_path),
        "known_limitations": [
            "Only the reviewed must-link edges are merged; unreviewed related scenes may remain.",
            "The uncertain reviewed pair is merged conservatively to avoid possible leakage.",
            "Existing filename-derived groups are retained, including potentially over-broad groups.",
            "This revision requires a complete repeated duplicate and visual audit before training.",
        ],
    }
    with (output_directory / "summary.json").open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
