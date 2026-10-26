#!/usr/bin/env python3
"""Second, stricter OCR pass over retained MmodalFire alignment frames.

This tool never changes source frames. It uses a narrow timestamp crop and a
digit-only OCR alphabet, then requires complete date-time parsing and temporal
progression before a video range can pass. The resulting ranges are alignment
assistance only; they are not event annotations.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path


# OCR commonly removes the separator between the date and clock or appends a
# stray digit to the seconds. Select the last syntactically valid HH:MM:SS and
# validate it through cross-sample progression instead of requiring word
# boundaries that the overlay does not reliably preserve.
TIME = re.compile(r"([01]\d|2[0-3]):([0-5]\d):([0-5]\d)")
YEAR = re.compile(r"20\d{2}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_timestamp(text: str) -> str | None:
    """Parse a timestamp even when Chinese separators become stray digits."""
    compact = " ".join(text.split())
    time_matches = list(TIME.finditer(compact))
    if not time_matches:
        return None
    time_match = time_matches[-1]
    prefix = compact[: time_match.start()]
    year_matches = list(YEAR.finditer(prefix))
    if not year_matches:
        return None
    year_match = year_matches[-1]
    year = int(year_match.group())
    suffix_digits = "".join(character for character in prefix[year_match.end() :] if character.isdigit())
    candidates: list[tuple[int, int, int]] = []
    for index in range(max(0, len(suffix_digits) - 7), len(suffix_digits) - 3):
        token = suffix_digits[index : index + 4]
        if len(token) != 4:
            continue
        month, day = int(token[:2]), int(token[2:])
        try:
            dt.date(year, month, day)
        except ValueError:
            continue
        candidates.append((index, month, day))
    if not candidates:
        return None
    _, month, day = candidates[-1]
    hour, minute, second = (int(value) for value in time_match.groups())
    return dt.datetime(year, month, day, hour, minute, second).isoformat()


def executable_version(executable: str, flag: str) -> str:
    completed = subprocess.run(
        [executable, flag], check=False, text=True, capture_output=True
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"version query failed: {executable}")
    output = completed.stdout or completed.stderr
    return output.splitlines()[0].strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alignment-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--tesseract", default="tesseract")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; OCR evidence is non-overwriting")

    source = json.loads(args.alignment_manifest.read_text(encoding="utf-8"))
    records: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="mmodal_ocr_v2_") as directory:
        temporary = Path(directory)
        for index, frame in enumerate(source["records"]):
            image = Path(frame["output"])
            if not image.is_file() or sha256(image) != frame["output_sha256"]:
                raise RuntimeError(f"alignment frame missing or hash changed: {image}")
            crop = temporary / f"crop_{index:03d}.png"
            crop_command = [
                args.ffmpeg, "-y", "-v", "error", "-i", str(image), "-vf",
                (
                    "crop=900:90:0:0,scale=3600:360:flags=lanczos,"
                    "format=gray,eq=contrast=2.0:brightness=0.05"
                ),
                str(crop),
            ]
            cropped = subprocess.run(
                crop_command, check=False, text=True, capture_output=True
            )
            ocr_command = [
                args.tesseract, str(crop), "stdout", "--psm", "6", "-l", "eng",
                "-c", "tessedit_char_whitelist=0123456789:-/",
            ]
            recognized = (
                subprocess.run(ocr_command, check=False, text=True, capture_output=True)
                if cropped.returncode == 0
                else None
            )
            raw = recognized.stdout.strip() if recognized is not None else ""
            timestamp = parse_timestamp(raw)
            status = (
                "TIMESTAMP_PARSED"
                if cropped.returncode == 0
                and recognized is not None
                and recognized.returncode == 0
                and timestamp is not None
                else "REVIEW_REQUIRED"
            )
            records.append(
                {
                    "video_file_name": frame["video_file_name"],
                    "video_sha256": frame["video_sha256"],
                    "sample_label": frame["sample_label"],
                    "requested_offset_seconds": frame["requested_offset_seconds"],
                    "source_frame": str(image),
                    "source_frame_sha256": frame["output_sha256"],
                    "crop_command": crop_command,
                    "crop_returncode": cropped.returncode,
                    "crop_stderr": cropped.stderr,
                    "ocr_command": ocr_command,
                    "ocr_returncode": (
                        recognized.returncode if recognized is not None else None
                    ),
                    "ocr_stdout_raw": raw,
                    "ocr_stderr": recognized.stderr if recognized is not None else "",
                    "parsed_timestamp": timestamp,
                    "status": status,
                }
            )

    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        grouped[record["video_file_name"]].append(record)
    progression: list[dict] = []
    for file_name, rows in sorted(grouped.items()):
        rows.sort(key=lambda row: row["requested_offset_seconds"])
        parsed = [row for row in rows if row["parsed_timestamp"]]
        checks: list[dict] = []
        for first, second in zip(parsed, parsed[1:]):
            first_time = dt.datetime.fromisoformat(first["parsed_timestamp"])
            second_time = dt.datetime.fromisoformat(second["parsed_timestamp"])
            observed = (second_time - first_time).total_seconds()
            expected = second["requested_offset_seconds"] - first["requested_offset_seconds"]
            error = abs(observed - expected)
            checks.append(
                {
                    "first_label": first["sample_label"],
                    "second_label": second["sample_label"],
                    "expected_delta_seconds": expected,
                    "observed_timestamp_delta_seconds": observed,
                    "absolute_error_seconds": error,
                    "within_two_seconds": error <= 2.0,
                }
            )
        strict_pass = (
            len(parsed) == len(rows)
            and len(checks) == max(0, len(rows) - 1)
            and bool(checks)
            and all(check["within_two_seconds"] for check in checks)
        )
        progression.append(
            {
                "video_file_name": file_name,
                "parsed_timestamp_count": len(parsed),
                "checks": checks,
                "status": "PASS" if strict_pass else "REVIEW_REQUIRED",
                "range_start": parsed[0]["parsed_timestamp"] if strict_pass else None,
                "range_end": parsed[-1]["parsed_timestamp"] if strict_pass else None,
            }
        )

    parsed_count = sum(row["status"] == "TIMESTAMP_PARSED" for row in records)
    pass_count = sum(row["status"] == "PASS" for row in progression)
    result = {
        "schema_version": 2,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": "OCR_COMPLETE_REVIEW_REQUIRED",
        "alignment_manifest": str(args.alignment_manifest),
        "alignment_manifest_sha256": sha256(args.alignment_manifest),
        "ffmpeg_version": executable_version(args.ffmpeg, "-version"),
        "tesseract_version": executable_version(args.tesseract, "--version"),
        "preprocessing": (
            "crop=900:90:0:0,scale=3600:360:flags=lanczos,format=gray,"
            "eq=contrast=2.0:brightness=0.05"
        ),
        "ocr_configuration": "psm=6; language=eng; whitelist=digits,colons,hyphen,slash",
        "frame_count": len(records),
        "parsed_timestamp_count": parsed_count,
        "review_required_frame_count": len(records) - parsed_count,
        "video_progression_pass_count": pass_count,
        "video_count": len(progression),
        "records": records,
        "progression_checks": progression,
        "acceptance_rule": (
            "All retained samples for a video must parse a full date-time and each "
            "timestamp delta must match the extraction-offset delta within two seconds."
        ),
        "claim_boundary": (
            "OCR-assisted video-range alignment only; event intervals require an "
            "independent publisher-timestamp or visual cross-check before admission"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "frame_count": len(records),
                "parsed_timestamp_count": parsed_count,
                "review_required_frame_count": len(records) - parsed_count,
                "video_progression_pass_count": pass_count,
                "output": str(args.output),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
