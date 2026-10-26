#!/usr/bin/env python3
"""Create a new immutable manifest from reviewed annotation actions."""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path

try:
    from apply_manual_duplicate_review import file_sha256, parse_index_ranges
    from audit_fire_annotations import load_records
except ImportError:
    from tools.apply_manual_duplicate_review import file_sha256, parse_index_ranges
    from tools.audit_fire_annotations import load_records


def apply_actions(records, decision_rows, adjudication):
    decisions_by_index = {int(row["queue_index"]): row for row in decision_rows}
    excluded_indices = set(parse_index_ranges(adjudication["exclude_record_indices"]))
    keep_specs = {
        int(queue_index): set(parse_index_ranges(specification))
        for queue_index, specification in adjudication["keep_box_indices_by_queue_index"].items()
    }
    overlap = excluded_indices & set(keep_specs)
    if overlap:
        raise ValueError("queue indices have both exclusion and box-filter actions: {}".format(sorted(overlap)))
    action_indices = excluded_indices | set(keep_specs)
    missing_indices = sorted(action_indices - set(decisions_by_index))
    if missing_indices:
        raise ValueError("adjudication indices absent from review decisions: {}".format(missing_indices))
    records_by_id = {record["record_id"]: record for record in records}
    excluded_record_ids = {decisions_by_index[index]["record_id"] for index in excluded_indices}
    filtered_by_record_id = {
        decisions_by_index[index]["record_id"]: keep_indices
        for index, keep_indices in keep_specs.items()
    }
    if excluded_record_ids & set(filtered_by_record_id):
        raise ValueError("record has both exclusion and box-filter actions")
    unknown_record_ids = sorted((excluded_record_ids | set(filtered_by_record_id)) - set(records_by_id))
    if unknown_record_ids:
        raise ValueError("reviewed record absent from manifest: {}".format(unknown_record_ids))
    output_records = []
    removed_boxes = 0
    filtered_records = []
    for record in records:
        record_id = record["record_id"]
        if record_id in excluded_record_ids:
            removed_boxes += len(record["derived_label_rows"])
            continue
        updated = dict(record)
        if record_id in filtered_by_record_id:
            rows = record["derived_label_rows"]
            keep_indices = filtered_by_record_id[record_id]
            invalid = sorted(index for index in keep_indices if index > len(rows))
            if invalid:
                raise ValueError("box indices exceed row count for {}: {}".format(record_id, invalid))
            kept_rows = [row for index, row in enumerate(rows, 1) if index in keep_indices]
            if not kept_rows:
                raise ValueError("box filtering would leave positive record empty: {}".format(record_id))
            removed_boxes += len(rows) - len(kept_rows)
            updated["derived_label_rows"] = kept_rows
            updated["annotation_adjudication"] = {
                "source_manifest_version": 9,
                "kept_original_box_indices": sorted(keep_indices),
            }
            filtered_records.append(record_id)
        output_records.append(updated)
    return output_records, {
        "excluded_record_ids": sorted(excluded_record_ids),
        "filtered_record_ids": sorted(filtered_records),
        "removed_box_count": removed_boxes,
    }


def summarize(records):
    split_counts = collections.defaultdict(lambda: {"total": 0, "positive": 0, "background": 0})
    group_splits = collections.defaultdict(set)
    box_count = 0
    for record in records:
        split = record["split"]
        split_counts[split]["total"] += 1
        split_counts[split]["positive" if record["category"] == "fire_positive" else "background"] += 1
        group_splits[record["group_id"]].add(split)
        box_count += len(record["derived_label_rows"])
    leaking_groups = {group: sorted(splits) for group, splits in group_splits.items() if len(splits) > 1}
    if leaking_groups:
        raise ValueError("group leakage after adjudication")
    return {
        "record_count": len(records),
        "box_count": box_count,
        "group_count": len(group_splits),
        "split_counts": {key: split_counts[key] for key in sorted(split_counts)},
        "cross_split_group_count": 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("records_jsonl")
    parser.add_argument("review_decisions_csv")
    parser.add_argument("adjudication_manifest")
    parser.add_argument("--render-manifest", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--dataset-id", required=True)
    arguments = parser.parse_args()
    records_path = Path(arguments.records_jsonl).resolve()
    decisions_path = Path(arguments.review_decisions_csv).resolve()
    adjudication_path = Path(arguments.adjudication_manifest).resolve()
    render_manifest_path = Path(arguments.render_manifest).resolve()
    output_directory = Path(arguments.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=False)
    adjudication = json.loads(adjudication_path.read_text(encoding="utf-8"))
    if file_sha256(decisions_path) != adjudication["review_decisions_csv_sha256"]:
        raise ValueError("review-decisions SHA-256 does not match adjudication")
    if file_sha256(render_manifest_path) != adjudication["adjudication_render_manifest_sha256"]:
        raise ValueError("render-manifest SHA-256 does not match adjudication")
    with decisions_path.open("r", encoding="utf-8", newline="") as source:
        decision_rows = list(csv.DictReader(source))
    records = load_records(records_path)
    output_records, actions = apply_actions(records, decision_rows, adjudication)
    output_records.sort(key=lambda record: (record["split"], record["group_id"], record["record_id"]))
    records_output_path = output_directory / "records.jsonl"
    with records_output_path.open("x", encoding="utf-8") as output:
        for record in output_records:
            output.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    summary = {
        "schema_version": 1,
        "dataset_id": arguments.dataset_id,
        "source_records_jsonl": str(records_path),
        "source_records_jsonl_sha256": file_sha256(records_path),
        "review_decisions_csv": str(decisions_path),
        "review_decisions_csv_sha256": file_sha256(decisions_path),
        "adjudication_manifest": str(adjudication_path),
        "adjudication_manifest_sha256": file_sha256(adjudication_path),
        "render_manifest": str(render_manifest_path),
        "render_manifest_sha256": file_sha256(render_manifest_path),
        "records_jsonl": str(records_output_path),
        "records_jsonl_sha256": file_sha256(records_output_path),
        "actions": actions,
        "statistics": summarize(output_records),
        "known_limitations": adjudication["interpretation"],
    }
    summary_path = output_directory / "summary.json"
    with summary_path.open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
