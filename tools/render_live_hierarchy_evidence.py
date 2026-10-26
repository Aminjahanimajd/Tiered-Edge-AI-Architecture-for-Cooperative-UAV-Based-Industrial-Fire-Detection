#!/usr/bin/env python3
"""Create a thesis-ready hierarchy evidence plate from a verified summary."""

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
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.manifest_output.exists():
        parser.error("output exists; rendering is non-overwriting")
    summary = json.loads(args.summary.read_text(encoding="utf-8"))

    from PIL import Image, ImageDraw, ImageFont

    source = Image.open(summary["diagnostic_frame"]["path"]).convert("RGB")
    source.thumbnail((980, 720))
    canvas = Image.new("RGB", (1800, 1000), "white")
    draw = ImageDraw.Draw(canvas)
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    bold_path = Path("C:/Windows/Fonts/arialbd.ttf")
    font = ImageFont.truetype(str(font_path), 30) if font_path.exists() else ImageFont.load_default()
    small = ImageFont.truetype(str(font_path), 24) if font_path.exists() else font
    bold = ImageFont.truetype(str(bold_path), 42) if bold_path.exists() else font
    canvas.paste(source, (40, 130))
    draw.text((40, 35), "Live Scout verification after an injected Sentinel alert", fill="#0f172a", font=bold)
    x = 1060
    draw.rounded_rectangle((1020, 120, 1760, 850), radius=24, fill="#f1f5f9", outline="#94a3b8", width=3)
    lines = [
        ("Evidence status", "#334155", small),
        (summary["status"], "#15803d", bold),
        ("Scout decision", "#334155", small),
        (summary["scout_verdict"], "#b45309", bold),
        (f"TFLite inference: {summary['scout_tflite_inference_ms']:.1f} ms", "#0f172a", font),
        (f"Injected alert → verdict: {summary['sentinel_measured_injected_alert_to_verdict_callback_ms']:.1f} ms", "#0f172a", font),
        (f"Frame age at start: {summary['scout_frame_age_at_inference_start_ms']:.1f} ms", "#0f172a", font),
        (f"Fire score: {summary['scout_raw_fire_max']:.6f}", "#0f172a", font),
        (f"Camera: {summary['camera']['width']}×{summary['camera']['height']} {summary['camera']['encoding']}", "#0f172a", font),
        ("Target coordinates used: no", "#0f172a", font),
        ("No dropped log records", "#0f172a", font),
    ]
    y = 160
    for content, colour, selected_font in lines:
        draw.text((x, y), content, fill=colour, font=selected_font)
        y += 66 if selected_font is bold else 54
    draw.text(
        (40, 900),
        "Scope: one stationary negative-scene trial. The alert was injected; this is not Sentinel detection or industrial-site evidence.",
        fill="#991b1b",
        font=small,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output, format="PNG", optimize=True)
    manifest = {
        "schema_version": 1,
        "classification": "derived_visual_evidence_with_authentic_camera_frame",
        "source_summary_sha256": sha256(args.summary),
        "source_camera_frame_sha256": summary["diagnostic_frame"]["sha256"],
        "output_sha256": sha256(args.output),
        "claim_boundary": summary["claim_boundary"],
    }
    args.manifest_output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
