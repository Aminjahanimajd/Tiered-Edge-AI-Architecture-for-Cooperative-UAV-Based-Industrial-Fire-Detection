#!/usr/bin/env python3
"""Validate the publisher-derived MmodalFire experiment-condition table."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADERS = [
    "Material",
    "Lighting Environment(lx)",
    "Wind speed (m/s)",
    "Location of fire",
    "Quantity of material",
    "Time",
    "Month.Day Hour:Min-Hour-Min",
]
EXPECTED_GROUPS = {
    "cotton": 9,
    "n_heptane": 8,
    "polyurethane": 5,
    "wood": 4,
    "dry_ice": 4,
    "mist": 4,
    "blank_control": 2,
    "occlusion": 2,
}
TIME_PATTERN = re.compile(
    r"^(?P<month>\d{1,2})\.(?P<day>\d{1,2}) "
    r"(?P<start_hour>\d{1,2}):(?P<start_minute>\d{2})-"
    r"(?P<end_hour>\d{1,2}):(?P<end_minute>\d{2})$"
)


def group_name(material: str) -> str:
    lower = material.lower().replace(" ", "")
    if lower.startswith("cotton"):
        return "cotton"
    if lower.startswith("n-heptane"):
        return "n_heptane"
    if lower.startswith("polyurethane"):
        return "polyurethane"
    if lower.startswith("wood"):
        return "wood"
    if lower.startswith("dryice"):
        return "dry_ice"
    if lower.startswith("mist"):
        return "mist"
    if lower.startswith("blankcontrol"):
        return "blank_control"
    if lower.startswith("occlusion"):
        return "occlusion"
    return "unknown"


def duration_minutes(value: str) -> int:
    match = TIME_PATTERN.fullmatch(value.replace("：", ":"))
    if not match:
        raise ValueError(f"invalid publisher time range: {value!r}")
    start = int(match["start_hour"]) * 60 + int(match["start_minute"])
    end = int(match["end_hour"]) * 60 + int(match["end_minute"])
    if end <= start:
        raise ValueError(f"non-positive publisher time range: {value!r}")
    return end - start


def validate(table: list) -> tuple[list[str], dict]:
    errors: list[str] = []
    if not table or table[0] != HEADERS:
        errors.append("header differs from the frozen publisher extraction")
    rows = table[1:] if table else []
    if len(rows) != 38:
        errors.append(f"expected 38 condition rows, found {len(rows)}")
    if any(not isinstance(row, list) or len(row) != 7 for row in rows):
        errors.append("every condition row must contain exactly seven cells")
        return errors, {"row_count": len(rows)}

    materials = [row[0] for row in rows]
    if len(set(materials)) != len(materials):
        errors.append("condition names are not unique")
    groups = Counter(group_name(str(material)) for material in materials)
    if dict(groups) != EXPECTED_GROUPS:
        errors.append(f"condition-group counts differ: {dict(groups)}")

    durations = []
    for row in rows:
        try:
            durations.append(duration_minutes(str(row[5])))
        except ValueError as exc:
            errors.append(str(exc))
    summary = {
        "row_count": len(rows),
        "group_counts": dict(sorted(groups.items())),
        "total_condition_minutes": sum(durations),
        "minimum_condition_minutes": min(durations) if durations else None,
        "maximum_condition_minutes": max(durations) if durations else None,
        "video_alignment_status": "REQUIRES_TIMESTAMP_ALIGNMENT_PER_PUBLISHER_README",
    }
    return errors, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--table",
        type=Path,
        default=ROOT / "config/mmodalfire_condition_table_v1.json",
    )
    args = parser.parse_args()
    table = json.loads(args.table.read_text(encoding="utf-8"))
    errors, summary = validate(table)
    print(json.dumps({
        "status": "PASS" if not errors else "FAIL",
        **summary,
        "errors": errors,
    }, indent=2, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
