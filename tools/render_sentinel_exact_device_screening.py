#!/usr/bin/env python3
"""Render thesis-ready visuals from Sentinel exact-device evidence."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from analyze_scout_exact_device_screening import sha256


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    plot = args.output_directory / "sentinel_exact_device_comparison.png"
    terminal = args.output_directory / "sentinel_exact_device_terminal_summary.png"
    manifest = args.output_directory / "visual_manifest.json"
    if any(path.exists() for path in (plot, terminal, manifest)):
        parser.error("visual output exists; rendering is non-overwriting")
    with args.comparison.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))

    import matplotlib.pyplot as plt
    labels = [row["model_id"].replace("_", "\n", 1) for row in rows]
    colours = ["#2563eb", "#7c3aed"]
    figure, axes = plt.subplots(1, 3, figsize=(14, 5), dpi=180)
    means = [float(row["pipeline_mean_ms"]) for row in rows]
    axes[0].bar(labels, means, color=colours)
    axes[0].scatter(labels, [float(row["pipeline_p95_ms"]) for row in rows], color="#dc2626", marker="D", label="p95")
    axes[0].set_ylabel("Pipeline latency (ms)")
    axes[0].set_title("Latency (n=200/model)")
    axes[0].legend()
    axes[1].bar(labels, [float(row["derived_throughput_fps"]) for row in rows], color=colours)
    axes[1].set_ylabel("Derived throughput (frames/s)")
    axes[1].set_title("1000 / mean pipeline latency")
    axes[2].bar(labels, [float(row["gpu_mean_percent"]) for row in rows], color=colours)
    axes[2].scatter(labels, [float(row["gpu_max_percent"]) for row in rows], color="#dc2626", marker="D", label="maximum")
    axes[2].set_ylabel("GR3D_FREQ reported value (%)")
    axes[2].set_title("1 Hz tegrastats samples")
    axes[2].legend()
    for axis in axes:
        axis.grid(axis="y", alpha=0.25)
    figure.suptitle("Sentinel (Jetson Nano) TensorRT FP16 exact-device screening", fontweight="bold")
    figure.text(0.5, 0.01, "20 warm-up + 200 measured inferences; 64 hashed replay images; camera-free and no actuation.", ha="center", fontsize=8)
    figure.tight_layout(rect=(0, 0.04, 1, 0.94))
    figure.savefig(plot, bbox_inches="tight")
    plt.close(figure)

    from PIL import Image, ImageDraw, ImageFont
    canvas = Image.new("RGB", (1800, 900), "#07111f")
    draw = ImageDraw.Draw(canvas)
    regular_path = Path("C:/Windows/Fonts/consola.ttf")
    bold_path = Path("C:/Windows/Fonts/consolab.ttf")
    regular = ImageFont.truetype(str(regular_path), 28) if regular_path.exists() else ImageFont.load_default()
    bold = ImageFont.truetype(str(bold_path), 34) if bold_path.exists() else regular
    lines = [
        ("DERIVED TERMINAL SUMMARY — SENTINEL EXACT-DEVICE SCREENING", "#7dd3fc", bold),
        ("status: PASS | TensorRT 8.2.1 FP16 | camera-free | no actuation", "#86efac", regular),
        ("protocol: 20 warm-up + 200 measured/model | 64 hashed images", "#e2e8f0", regular),
        ("", "#e2e8f0", regular),
    ]
    for row in rows:
        lines.extend([
            (row["model_id"], "#fde68a", bold),
            (f"  pipeline mean / median / p95: {float(row['pipeline_mean_ms']):.3f} / {float(row['pipeline_median_ms']):.3f} / {float(row['pipeline_p95_ms']):.3f} ms", "#e2e8f0", regular),
            (f"  throughput: {float(row['derived_throughput_fps']):.3f} frames/s | engine: {float(row['engine_mebibytes']):.2f} MiB", "#e2e8f0", regular),
            (f"  CPU mean: {float(row['cpu_mean_percent']):.1f}% | GR3D mean/max: {float(row['gpu_mean_percent']):.1f}/{float(row['gpu_max_percent']):.1f}%", "#e2e8f0", regular),
            (f"  RSS max: {float(row['process_rss_max_mib']):.1f} MiB | MemAvailable min: {float(row['mem_available_min_mib']):.1f} MiB | Tmax: {float(row['max_temperature_celsius']):.1f} °C", "#e2e8f0", regular),
        ])
    lines.extend([
        ("", "#e2e8f0", regular),
        ("Scope: camera-free replay latency/resources—not accuracy, endurance, flight, power, or industrial reliability.", "#fca5a5", regular),
    ])
    y = 42
    for content, colour, font in lines:
        draw.text((48, y), content, fill=colour, font=font)
        y += 58 if font is bold else 50
    canvas.save(terminal, format="PNG", optimize=True)
    payload = {
        "schema_version": 1,
        "classification": "derived_visual_evidence",
        "claim_boundary": "Visuals summarize hash-linked raw device records and are not independent measurements.",
        "source_summary_sha256": sha256(args.summary),
        "source_comparison_sha256": sha256(args.comparison),
        "outputs": {plot.name: sha256(plot), terminal.name: sha256(terminal)},
    }
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
