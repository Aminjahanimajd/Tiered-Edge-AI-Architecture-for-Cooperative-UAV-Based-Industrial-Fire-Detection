#!/usr/bin/env python3
"""Render a terminal-style summary of the receive-only Pixhawk capture."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    output = args.output_directory / "pixhawk_readonly_terminal_summary.png"
    manifest = args.output_directory / "visual_manifest.json"
    if output.exists() or manifest.exists():
        parser.error("output exists; rendering is non-overwriting")

    result = json.loads(args.analysis.read_text(encoding="utf-8"))
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1800, 1040), "#07111f")
    draw = ImageDraw.Draw(image)
    normal_path = Path("C:/Windows/Fonts/consola.ttf")
    bold_path = Path("C:/Windows/Fonts/consolab.ttf")
    normal = ImageFont.truetype(str(normal_path), 28) if normal_path.exists() else ImageFont.load_default()
    bold = ImageFont.truetype(str(bold_path), 35) if bold_path.exists() else normal
    counts = result["selected_message_type_counts"]
    lines = [
        ("PIXHAWK RECEIVE-ONLY MAVLINK — HASH-LINKED SUMMARY", "#7dd3fc", bold),
        (f"status: {result['status']}", "#86efac", normal),
        (f"duration / messages: {result['duration_seconds']:.3f} s / {result['message_count']}", "#e2e8f0", normal),
        (f"HEARTBEAT / ESTIMATOR_STATUS: {counts['HEARTBEAT']} / {counts['ESTIMATOR_STATUS']}", "#fde68a", normal),
        (f"GPS_RAW_INT / LOCAL_POSITION_NED / ODOMETRY: {counts['GPS_RAW_INT']} / {counts['LOCAL_POSITION_NED']} / {counts['ODOMETRY']}", "#e2e8f0", normal),
        (f"BATTERY_STATUS / SYS_STATUS / VIBRATION: {counts['BATTERY_STATUS']} / {counts['SYS_STATUS']} / {counts['VIBRATION']}", "#e2e8f0", normal),
        (f"MAVProxy restored active: {'yes' if result['mavproxy_restored_active'] else 'no'}", "#86efac", normal),
        ("", "#e2e8f0", normal),
        ("Safety: propellers removed; receive-only probe; no vehicle command sent.", "#fde68a", normal),
        ("Scope: telemetry availability and message-type presence in one stationary interval.", "#fca5a5", normal),
        ("Not estimator validity, localization accuracy, command routing, or flight readiness.", "#fca5a5", normal),
    ]
    y = 50
    for content, colour, font in lines:
        draw.text((50, y), content, fill=colour, font=font)
        y += 76 if font is bold else 67
    image.save(output, format="PNG", optimize=True)
    record = {
        "schema_version": 1,
        "classification": "derived_visual_evidence",
        "source_analysis_sha256": sha256(args.analysis),
        "outputs": {output.name: sha256(output)},
        "claim_boundary": result["claim_boundary"],
    }
    manifest.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
