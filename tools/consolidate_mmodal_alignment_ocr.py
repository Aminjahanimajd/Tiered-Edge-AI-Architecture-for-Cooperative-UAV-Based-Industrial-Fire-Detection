#!/usr/bin/env python3
"""Fail-closed consolidation of independent MmodalFire OCR passes."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import itertools
import json
from collections import defaultdict
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _timestamp(date_value: dt.date, clock: str) -> str:
    hour, minute, second = (int(value) for value in clock.split(":"))
    return dt.datetime.combine(date_value, dt.time(hour, minute, second)).isoformat()


def consolidate_video(v1_rows: list[dict], v2_rows: list[dict]) -> dict:
    """Return PASS only when the evidence yields one valid timestamp tuple."""
    v1_by_key = {
        (row["sample_label"], row["source_frame_sha256"]): row for row in v1_rows
    }
    v2_by_key = {
        (row["sample_label"], row["source_frame_sha256"]): row for row in v2_rows
    }
    if set(v1_by_key) != set(v2_by_key):
        return {"status": "REVIEW_REQUIRED", "reason": "FRAME_IDENTITY_MISMATCH"}

    parsed_v2 = [
        dt.datetime.fromisoformat(row["parsed_timestamp"])
        for row in v2_rows
        if row.get("parsed_timestamp")
    ]
    dates = {value.date() for value in parsed_v2}
    if len(dates) != 1:
        return {
            "status": "REVIEW_REQUIRED",
            "reason": "NO_UNIQUE_VIDEO_DATE",
            "observed_dates": sorted(value.isoformat() for value in dates),
        }
    video_date = next(iter(dates))

    ordered_keys = sorted(
        v1_by_key,
        key=lambda key: float(v1_by_key[key]["requested_offset_seconds"]),
    )
    candidate_sets: list[list[dict]] = []
    for key in ordered_keys:
        first = v1_by_key[key]
        second = v2_by_key[key]
        candidates: dict[str, set[str]] = defaultdict(set)
        if second.get("parsed_timestamp"):
            candidates[second["parsed_timestamp"]].add("v2_full_datetime")
        if first.get("parsed_clock_hh_mm_ss"):
            candidates[_timestamp(video_date, first["parsed_clock_hh_mm_ss"])].add(
                "v1_clock_plus_v2_date"
            )
        if not candidates:
            return {
                "status": "REVIEW_REQUIRED",
                "reason": "SAMPLE_WITHOUT_TIMESTAMP_CANDIDATE",
                "sample_label": key[0],
                "video_date": video_date.isoformat(),
            }
        candidate_sets.append(
            [
                {"timestamp": value, "origins": sorted(origins)}
                for value, origins in sorted(candidates.items())
            ]
        )

    valid: dict[tuple[str, ...], dict] = {}
    offsets = [float(v1_by_key[key]["requested_offset_seconds"]) for key in ordered_keys]
    for selection in itertools.product(*candidate_sets):
        timestamps = [dt.datetime.fromisoformat(item["timestamp"]) for item in selection]
        checks = []
        for index in range(len(timestamps) - 1):
            observed = (timestamps[index + 1] - timestamps[index]).total_seconds()
            expected = offsets[index + 1] - offsets[index]
            error = abs(observed - expected)
            checks.append(
                {
                    "first_label": ordered_keys[index][0],
                    "second_label": ordered_keys[index + 1][0],
                    "expected_delta_seconds": expected,
                    "observed_timestamp_delta_seconds": observed,
                    "absolute_error_seconds": error,
                    "within_two_seconds": error <= 2.0,
                }
            )
        if checks and all(check["within_two_seconds"] for check in checks):
            key = tuple(item["timestamp"] for item in selection)
            valid[key] = {
                "timestamps": list(key),
                "origins": [item["origins"] for item in selection],
                "checks": checks,
            }

    if len(valid) != 1:
        return {
            "status": "REVIEW_REQUIRED",
            "reason": "NO_UNIQUE_PROGRESSING_TIMESTAMP_TUPLE",
            "video_date": video_date.isoformat(),
            "valid_tuple_count": len(valid),
        }
    selected = next(iter(valid.values()))
    return {
        "status": "PASS",
        "reason": "UNIQUE_PROGRESSING_TIMESTAMP_TUPLE",
        "video_date": video_date.isoformat(),
        "range_start": selected["timestamps"][0],
        "range_end": selected["timestamps"][-1],
        "sample_timestamps": [
            {
                "sample_label": key[0],
                "source_frame_sha256": key[1],
                "requested_offset_seconds": offsets[index],
                "timestamp": selected["timestamps"][index],
                "origins": selected["origins"][index],
            }
            for index, key in enumerate(ordered_keys)
        ],
        "checks": selected["checks"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v1", type=Path, required=True)
    parser.add_argument("--v2", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; consolidation evidence is non-overwriting")

    v1 = json.loads(args.v1.read_text(encoding="utf-8"))
    v2 = json.loads(args.v2.read_text(encoding="utf-8"))
    grouped_v1: dict[str, list[dict]] = defaultdict(list)
    grouped_v2: dict[str, list[dict]] = defaultdict(list)
    for row in v1["records"]:
        grouped_v1[row["video_file_name"]].append(row)
    for row in v2["records"]:
        grouped_v2[row["video_file_name"]].append(row)
    if set(grouped_v1) != set(grouped_v2):
        raise RuntimeError("OCR manifests cover different video sets")

    records = []
    for file_name in sorted(grouped_v1):
        result = consolidate_video(grouped_v1[file_name], grouped_v2[file_name])
        records.append({"video_file_name": file_name, **result})
    pass_count = sum(record["status"] == "PASS" for record in records)
    output = {
        "schema_version": 1,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": "CONSOLIDATED_REVIEW_REQUIRED",
        "v1_manifest": str(args.v1),
        "v1_manifest_sha256": sha256(args.v1),
        "v2_manifest": str(args.v2),
        "v2_manifest_sha256": sha256(args.v2),
        "video_count": len(records),
        "video_pass_count": pass_count,
        "video_review_required_count": len(records) - pass_count,
        "records": records,
        "acceptance_rule": (
            "Frame identities must match, the v2 evidence must yield one video date, "
            "and all OCR candidates must yield exactly one timestamp tuple whose "
            "progression agrees with frame offsets within two seconds."
        ),
        "claim_boundary": (
            "OCR-assisted video-range alignment only; event intervals require an "
            "independent publisher-timestamp or visual cross-check before admission"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(output, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "status": output["status"],
                "video_count": len(records),
                "video_pass_count": pass_count,
                "video_review_required_count": len(records) - pass_count,
                "output": str(args.output),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
