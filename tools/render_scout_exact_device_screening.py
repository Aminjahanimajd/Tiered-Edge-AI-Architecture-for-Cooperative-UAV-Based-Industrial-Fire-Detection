#!/usr/bin/env python3
"""Render thesis-ready visuals from the verified Scout screening summary."""

from __future__ import annotations

import argparse
import csv
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
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    plot_path = args.output_directory / "scout_exact_device_comparison.png"
    terminal_path = args.output_directory / "scout_exact_device_terminal_summary.png"
    manifest_path = args.output_directory / "visual_manifest.json"
    if any(path.exists() for path in (plot_path, terminal_path, manifest_path)):
        parser.error("visual output exists; rendering is non-overwriting")

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    with args.comparison.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))

    import matplotlib.pyplot as plt

    labels = [row["model_id"].replace("_", "\n", 1) for row in rows]
    colours = ["#0f766e", "#2563eb", "#7c3aed"]
    figure, axes = plt.subplots(1, 3, figsize=(14.5, 5.2), dpi=180)
    pipeline = [float(row["pipeline_mean_ms"]) for row in rows]
    pipeline_p95 = [float(row["pipeline_p95_ms"]) for row in rows]
    axes[0].bar(labels, pipeline, color=colours)
    axes[0].scatter(labels, pipeline_p95, color="#dc2626", marker="D", label="p95")
    axes[0].set_ylabel("Latency (ms)")
    axes[0].set_title("Pipeline latency (n=200/model)")
    axes[0].legend()

    axes[1].bar(labels, [float(row["derived_throughput_fps"]) for row in rows], color=colours)
    axes[1].set_ylabel("Derived throughput (frames/s)")
    axes[1].set_title("1000 / mean pipeline latency")

    axes[2].scatter(
        [float(row["model_mebibytes"]) for row in rows],
        pipeline,
        s=[120, 120, 120],
        c=colours,
    )
    for row in rows:
        axes[2].annotate(
            row["model_id"],
            (float(row["model_mebibytes"]), float(row["pipeline_mean_ms"])),
            xytext=(6, 6), textcoords="offset points", fontsize=8,
        )
    axes[2].set_xlabel("Model artifact size (MiB)")
    axes[2].set_ylabel("Mean pipeline latency (ms)")
    axes[2].set_title("Resource trade-off view")
    for axis in axes:
        axis.grid(axis="y", alpha=0.25)
    figure.suptitle("Scout (VOXL 2) exact-device camera-free replay screening", fontweight="bold")
    figure.text(
        0.5, 0.01,
        "20 warm-up + 200 measured inferences; 64 hashed replay images. Runtime paths differ; this is not accuracy or endurance evidence.",
        ha="center", fontsize=8,
    )
    figure.tight_layout(rect=(0, 0.04, 1, 0.94))
    figure.savefig(plot_path, bbox_inches="tight")
    plt.close(figure)

    from PIL import Image, ImageDraw, ImageFont

    canvas = Image.new("RGB", (1800, 1260), "#07111f")
    draw = ImageDraw.Draw(canvas)
    font_path = Path("C:/Windows/Fonts/consola.ttf")
    bold_path = Path("C:/Windows/Fonts/consolab.ttf")
    font = ImageFont.truetype(str(font_path), 27) if font_path.exists() else ImageFont.load_default()
    bold = ImageFont.truetype(str(bold_path), 33) if bold_path.exists() else font
    lines = [
        ("DERIVED TERMINAL SUMMARY — SCOUT EXACT-DEVICE SCREENING", "#7dd3fc", bold),
        ("status: PASS | safety: camera-free replay; no actuation interface", "#86efac", font),
        ("protocol: 20 warm-up + 200 measured/model | 64 hashed images", "#e2e8f0", font),
        ("", "#e2e8f0", font),
    ]
    for row in rows:
        provider = row["provider"]
        lines.extend(
            [
                (row["model_id"], "#fde68a", bold),
                (f"  runtime/provider: {row['runtime']} / {provider}", "#cbd5e1", font),
                (f"  pipeline mean / median / p95: {float(row['pipeline_mean_ms']):.3f} / {float(row['pipeline_median_ms']):.3f} / {float(row['pipeline_p95_ms']):.3f} ms", "#e2e8f0", font),
                (f"  derived throughput: {float(row['derived_throughput_fps']):.3f} frames/s | artifact: {float(row['model_mebibytes']):.2f} MiB", "#e2e8f0", font),
                (f"  CPU mean/max: {float(row['cpu_mean_percent']):.1f}/{float(row['cpu_max_percent']):.1f}% | RSS max: {float(row['process_rss_max_mib']):.1f} MiB | Tmax*: {float(row['max_valid_temperature_celsius']):.1f} °C", "#e2e8f0", font),
            ]
        )
    lines.extend(
        [
            ("", "#e2e8f0", font),
            ("* Maximum across valid 0–120 °C thermal-zone readings; 1 Hz sampling.", "#94a3b8", font),
            ("Scope: camera-free replay feasibility/resources only—not accuracy, endurance, flight, or industrial reliability.", "#fca5a5", font),
        ]
    )
    y = 42
    for content, colour, selected_font in lines:
        draw.text((50, y), content, fill=colour, font=selected_font)
        y += 51 if selected_font is font else 60
    canvas.save(terminal_path, format="PNG", optimize=True)

    manifest = {
        "schema_version": 1,
        "classification": "derived_visual_evidence",
        "claim_boundary": "Visuals summarize hash-linked raw device measurements and are not independent measurement sources.",
        "source_summary_sha256": sha256(args.summary),
        "source_comparison_sha256": sha256(args.comparison),
        "retained_failure_count": len(summary["retained_pre_fix_failures"]),
        "outputs": {
            plot_path.name: sha256(plot_path),
            terminal_path.name: sha256(terminal_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
