#!/usr/bin/env python3
"""Join a source-controlled annotation-review manifest to its audit queue."""

from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path

try:
    from apply_manual_duplicate_review import build_labels, file_sha256
except ImportError:
    from tools.apply_manual_duplicate_review import build_labels, file_sha256


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
    fieldnames = list(rows[0])
    with output_csv_path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for index, row in enumerate(rows, 1):
            enriched = dict(row)
            enriched["manual_classification"] = labels[index]
            writer.writerow(enriched)
    counts = collections.Counter(labels.values())
    summary = {
        "schema_version": 1,
        "review_queue_csv": str(queue_path),
        "review_queue_csv_sha256": observed_hash,
        "decision_manifest": str(manifest_path),
        "decision_manifest_sha256": file_sha256(manifest_path),
        "reviewed_image_count": len(rows),
        "classification_counts": dict(sorted(counts.items())),
        "output_csv": str(output_csv_path),
        "classification_definitions": manifest["classification_definitions"],
        "interpretation": manifest["interpretation"],
    }
    with output_summary_path.open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
