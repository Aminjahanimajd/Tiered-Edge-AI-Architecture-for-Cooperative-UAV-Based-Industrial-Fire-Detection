#!/usr/bin/env python3
"""OCR visible clock overlays from deterministic MmodalFire alignment frames."""

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


CLOCK = re.compile(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d):([0-5]\d)(?!\d)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_clock(text: str) -> str | None:
    matches = CLOCK.findall(text)
    if not matches:
        return None
    hour, minute, second = matches[-1]
    return f"{int(hour):02d}:{minute}:{second}"


def clock_seconds(value: str) -> int:
    hour, minute, second = [int(part) for part in value.split(":")]
    return hour * 3600 + minute * 60 + second


def circular_delta_seconds(first: str, second: str) -> int:
    return (clock_seconds(second) - clock_seconds(first)) % 86400


def version(executable: str, flag: str) -> str:
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
    records = []
    with tempfile.TemporaryDirectory(prefix="mmodal_ocr_") as directory:
        temporary = Path(directory)
        for index, frame in enumerate(source["records"]):
            image = Path(frame["output"])
            if not image.is_file() or sha256(image) != frame["output_sha256"]:
                raise RuntimeError(f"alignment frame missing or hash changed: {image}")
            crop = temporary / f"crop_{index:03d}.png"
            crop_command = [
                args.ffmpeg, "-y", "-v", "error", "-i", str(image),
                "-vf", "crop=1100:70:20:0,scale=2200:140:flags=lanczos",
                str(crop),
            ]
            cropped = subprocess.run(crop_command, check=False, text=True, capture_output=True)
            ocr_command = [
                args.tesseract, str(crop), "stdout", "--psm", "7", "-l", "chi_sim+eng"
            ]
            recognized = subprocess.run(
                ocr_command, check=False, text=True, capture_output=True
            ) if cropped.returncode == 0 else None
            raw = recognized.stdout.strip() if recognized is not None else ""
            clock = parse_clock(raw)
            status = (
                "CLOCK_PARSED"
                if cropped.returncode == 0 and recognized is not None
                and recognized.returncode == 0 and clock is not None
                else "REVIEW_REQUIRED"
            )
            records.append({
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
                "ocr_returncode": recognized.returncode if recognized is not None else None,
                "ocr_stdout_raw": raw,
                "ocr_stderr": recognized.stderr if recognized is not None else "",
                "parsed_clock_hh_mm_ss": clock,
                "status": status,
            })

    grouped = defaultdict(list)
    for record in records:
        grouped[record["video_file_name"]].append(record)
    progression = []
    for file_name, rows in sorted(grouped.items()):
        rows.sort(key=lambda row: row["requested_offset_seconds"])
        parsed = [row for row in rows if row["parsed_clock_hh_mm_ss"]]
        checks = []
        for first, second in zip(parsed, parsed[1:]):
            observed = circular_delta_seconds(
                first["parsed_clock_hh_mm_ss"], second["parsed_clock_hh_mm_ss"]
            )
            expected = second["requested_offset_seconds"] - first["requested_offset_seconds"]
            checks.append({
                "first_label": first["sample_label"],
                "second_label": second["sample_label"],
                "expected_delta_seconds": expected,
                "observed_clock_delta_seconds": observed,
                "absolute_error_seconds": abs(observed - expected),
                "within_two_seconds": abs(observed - expected) <= 2.0,
            })
        progression.append({
            "video_file_name": file_name,
            "parsed_clock_count": len(parsed),
            "checks": checks,
            "status": (
                "PASS" if len(parsed) == len(rows) and checks
                and all(check["within_two_seconds"] for check in checks)
                else "REVIEW_REQUIRED"
            ),
        })

    parsed_count = sum(record["status"] == "CLOCK_PARSED" for record in records)
    progression_pass_count = sum(row["status"] == "PASS" for row in progression)
    result = {
        "schema_version": 1,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": "OCR_COMPLETE_REVIEW_REQUIRED",
        "alignment_manifest": str(args.alignment_manifest),
        "alignment_manifest_sha256": sha256(args.alignment_manifest),
        "ffmpeg_version": version(args.ffmpeg, "-version"),
        "tesseract_version": version(args.tesseract, "--version"),
        "preprocessing": "crop=1100:70:20:0,scale=2200:140:flags=lanczos",
        "ocr_configuration": "psm=7; languages=chi_sim+eng",
        "frame_count": len(records),
        "parsed_clock_count": parsed_count,
        "review_required_count": len(records) - parsed_count,
        "video_progression_pass_count": progression_pass_count,
        "video_count": len(progression),
        "records": records,
        "progression_checks": progression,
        "acceptance_rule": (
            "OCR is provisional even when parsed; every admitted interval requires visual or "
            "publisher-timestamp cross-check. Clock progression tolerance is two seconds."
        ),
        "claim_boundary": "OCR assistance only; not authoritative event labeling",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({
        "status": result["status"],
        "frame_count": len(records),
        "parsed_clock_count": parsed_count,
        "review_required_count": len(records) - parsed_count,
        "video_progression_pass_count": progression_pass_count,
        "output": str(args.output),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
