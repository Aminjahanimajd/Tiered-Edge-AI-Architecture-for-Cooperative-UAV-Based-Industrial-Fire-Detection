#!/usr/bin/env python3
"""Join a source-controlled visual-review decision manifest to a review queue."""

from __future__ import print_function

import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_index_ranges(specification):
    indices = []
    for component in specification.split(","):
        component = component.strip()
        if not component:
            raise ValueError("empty index-range component")
        if "-" in component:
            first_text, last_text = component.split("-", 1)
            first = int(first_text)
            last = int(last_text)
            if first > last:
                raise ValueError("descending index range: {}".format(component))
            indices.extend(range(first, last + 1))
        else:
            indices.append(int(component))
    if any(index < 1 for index in indices):
        raise ValueError("review indices are one-based positive integers")
    if len(indices) != len(set(indices)):
        raise ValueError("duplicate index inside range specification")
    return indices


def build_labels(classifications, row_count):
    labels = {}
    for label, specification in classifications.items():
        for index in parse_index_ranges(specification):
            if index > row_count:
                raise ValueError("review index {} exceeds queue length".format(index))
            if index in labels:
                raise ValueError("review index {} has multiple labels".format(index))
            labels[index] = label
    expected = set(range(1, row_count + 1))
    missing = sorted(expected - set(labels))
    if missing:
        raise ValueError("unlabelled review indices: {}".format(missing))
    return labels


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("review_queue_csv")
    parser.add_argument("decision_manifest")
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--output-summary", required=True)
    arguments = parser.parse_args()
    queue_path = Path(arguments.review_queue_csv).resolve()
    manifest_path = Path(arguments.decision_manifest).resolve()
    output_csv_path = Path(arguments.output_csv).resolve()
    output_summary_path = Path(arguments.output_summary).resolve()
    for output in (output_csv_path, output_summary_path):
        if output.exists():
            raise FileExistsError("output already exists: {}".format(output))
        output.parent.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    observed_hash = file_sha256(queue_path)
    if observed_hash != manifest["queue_csv_sha256"]:
        raise ValueError("review queue SHA-256 does not match decision manifest")
    with queue_path.open("r", encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    labels = build_labels(manifest["classifications"], len(rows))
    fieldnames = ["review_index"] + list(rows[0]) + ["visual_label"]
    with output_csv_path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for index, row in enumerate(rows, 1):
            enriched = {"review_index": index}
            enriched.update(row)
            enriched["visual_label"] = labels[index]
            writer.writerow(enriched)
    counts = collections.Counter(labels.values())
    summary = {
        "schema_version": 1,
        "review_queue_csv": str(queue_path),
        "review_queue_csv_sha256": observed_hash,
        "decision_manifest": str(manifest_path),
        "decision_manifest_sha256": file_sha256(manifest_path),
        "reviewed_pair_count": len(rows),
        "classification_counts": dict(sorted(counts.items())),
        "output_csv": str(output_csv_path),
        "interpretation": manifest["interpretation"],
    }
    with output_summary_path.open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
