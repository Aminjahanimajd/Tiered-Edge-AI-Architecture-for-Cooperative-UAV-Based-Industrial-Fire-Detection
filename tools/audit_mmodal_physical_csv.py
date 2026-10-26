#!/usr/bin/env python3
"""Hash and inventory publisher MmodalFire physical-data CSV pairs."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
from pathlib import Path


TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def timestamp_summary(path: Path) -> dict:
    timestamps: list[list[str]] = []
    row_count = 0
    with path.open("r", encoding="latin-1", newline="") as stream:
        reader = csv.reader(stream)
        next(reader, None)
        for row in reader:
            if not row:
                continue
            row_count += 1
            parsed = [value.strip() for value in row if TIMESTAMP.fullmatch(value.strip())]
            if parsed:
                timestamps.append(parsed)
    if not timestamps:
        return {"data_row_count": row_count, "timestamp_status": "NO_TIMESTAMP_COLUMNS"}
    column_count = len(timestamps[0])
    if any(len(row) != column_count for row in timestamps) or len(timestamps) != row_count:
        return {
            "data_row_count": row_count,
            "timestamp_status": "MALFORMED_OR_PARTIAL_TIMESTAMP_ROWS",
        }
    columns = list(zip(*timestamps))
    return {
        "data_row_count": row_count,
        "timestamp_status": "PASS",
        "timestamp_column_count": column_count,
        "first_timestamps": [column[0] for column in columns],
        "last_timestamps": [column[-1] for column in columns],
    }


def build(root: Path) -> tuple[dict, list[str]]:
    paths = sorted(root.glob("*.csv"), key=lambda path: path.name.lower())
    if not paths:
        raise ValueError("no CSV files found")
    errors = []
    records = []
    for path in paths:
        summary = timestamp_summary(path)
        if summary["timestamp_status"] == "MALFORMED_OR_PARTIAL_TIMESTAMP_ROWS":
            errors.append(f"malformed or partial timestamps in {path.name!r}")
        records.append({
            "file_name": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            **summary,
        })
    timestamp_count = sum(row["timestamp_status"] == "PASS" for row in records)
    measurement_count = sum(
        row["timestamp_status"] == "NO_TIMESTAMP_COLUMNS" for row in records
    )
    manifest = {
        "schema_version": 1,
        "manifest_id": "mmodalfire_physical_csv_inventory_v1",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": "PASS" if not errors else "FAIL",
        "source_root": str(root),
        "csv_file_count": len(paths),
        "timestamp_csv_count": timestamp_count,
        "measurement_csv_count": measurement_count,
        "records": records,
        "errors": errors,
        "claim_boundary": (
            "publisher physical-data file and timestamp inventory; filename pairing and "
            "condition-to-video mapping still require explicit alignment"
        ),
    }
    return manifest, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest, errors = build(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({
        "status": manifest["status"],
        "csv_file_count": manifest["csv_file_count"],
        "timestamp_csv_count": manifest["timestamp_csv_count"],
        "measurement_csv_count": manifest["measurement_csv_count"],
        "error_count": len(errors),
        "output": str(args.output),
    }))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
