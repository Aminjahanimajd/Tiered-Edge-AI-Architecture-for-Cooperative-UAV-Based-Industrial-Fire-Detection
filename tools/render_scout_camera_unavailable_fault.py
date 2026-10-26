#!/usr/bin/env python3
"""Render a terminal-style panel for the Scout no-frame fault result."""

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
    output = args.output_directory / "scout_camera_unavailable_terminal_summary.png"
    manifest = args.output_directory / "visual_manifest.json"
    if output.exists() or manifest.exists():
        parser.error("output exists; rendering is non-overwriting")

    result = json.loads(args.analysis.read_text(encoding="utf-8"))
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1600, 900), "#07111f")
    draw = ImageDraw.Draw(image)
    normal_path = Path("C:/Windows/Fonts/consola.ttf")
    bold_path = Path("C:/Windows/Fonts/consolab.ttf")
    normal = ImageFont.truetype(str(normal_path), 29) if normal_path.exists() else ImageFont.load_default()
    bold = ImageFont.truetype(str(bold_path), 35) if bold_path.exists() else normal
    latency = result["latency_ms"]
    lines = [
        ("SCOUT CAMERA-INTERFACE FAULT — HASH-LINKED SUMMARY", "#7dd3fc", bold),
        (f"status: {result['status']}", "#86efac", normal),
        (f"fault: {result['fault']}", "#e2e8f0", normal),
        (f"correlated fail-closed verdicts: {result['correlated_error_verdicts']}/{result['expected_repetitions']}", "#e2e8f0", normal),
        (f"verdict / reason: ERROR / {result['reason']}", "#fde68a", normal),
        (f"verification inferences executed: {result['verification_inference_count']}", "#e2e8f0", normal),
        (f"latency mean / median / p95: {latency['mean']:.3f} / {latency['median']:.3f} / {latency['p95']:.3f} ms", "#fde68a", normal),
        (f"bounded node exit code: {result['node_exit_code']}", "#e2e8f0", normal),
        ("", "#e2e8f0", normal),
        ("Scope: ROS camera bridge intentionally absent; underlying camera service unchanged.", "#fca5a5", normal),
        ("Not evidence of physical camera-hardware failure, flight, or industrial reliability.", "#fca5a5", normal),
    ]
    y = 52
    for content, colour, font in lines:
        draw.text((52, y), content, fill=colour, font=font)
        y += 68 if font is bold else 58
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
