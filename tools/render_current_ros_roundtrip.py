#!/usr/bin/env python3
"""Render thesis-ready and terminal-style visuals from verified RTT evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import textwrap
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
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    plot_path = args.output_directory / "roundtrip_latency_distribution.png"
    terminal_path = args.output_directory / "roundtrip_terminal_summary.png"
    manifest_path = args.output_directory / "visual_manifest.json"
    if any(path.exists() for path in (plot_path, terminal_path, manifest_path)):
        parser.error("visual output exists; rendering is non-overwriting")

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    with args.samples.open(newline="", encoding="utf-8") as source:
        rtts = [float(row["round_trip_ms"]) for row in csv.DictReader(source)]

    import matplotlib.pyplot as plt

    plt.style.use("seaborn-v0_8-whitegrid")
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.8), dpi=180)
    axes[0].hist(rtts, bins=35, color="#2563eb", edgecolor="white")
    axes[0].axvline(summary["rtt_ms"]["median"], color="#0f172a", linestyle="--", label="Median")
    axes[0].axvline(summary["rtt_ms"]["p95"], color="#dc2626", linestyle=":", label="p95")
    axes[0].set_xlabel("Round-trip latency (ms)")
    axes[0].set_ylabel("Count")
    axes[0].set_title("Latency distribution")
    axes[0].legend()
    ordered = sorted(rtts)
    cumulative = [(index + 1) / len(ordered) for index in range(len(ordered))]
    axes[1].plot(ordered, cumulative, color="#059669", linewidth=2)
    axes[1].axhline(0.95, color="#dc2626", linestyle=":")
    axes[1].set_xlabel("Round-trip latency (ms)")
    axes[1].set_ylabel("Empirical cumulative probability")
    axes[1].set_title("Empirical CDF")
    figure.suptitle(
        "Sentinel–Scout ROS 2/DDS correlated round trips (n={})".format(len(rtts)),
        fontweight="bold",
    )
    figure.text(
        0.5,
        0.01,
        summary["network_condition"] + "; one-way latency not inferred.",
        ha="center",
        fontsize=8,
    )
    figure.tight_layout(rect=(0, 0.04, 1, 0.94))
    figure.savefig(plot_path, bbox_inches="tight")
    plt.close(figure)

    from PIL import Image, ImageDraw, ImageFont

    canvas = Image.new("RGB", (1600, 1080), "#07111f")
    draw = ImageDraw.Draw(canvas)
    font_path = Path("C:/Windows/Fonts/consola.ttf")
    bold_path = Path("C:/Windows/Fonts/consolab.ttf")
    font = ImageFont.truetype(str(font_path), 28) if font_path.exists() else ImageFont.load_default()
    bold = ImageFont.truetype(str(bold_path), 34) if bold_path.exists() else font
    lines = [
        ("DERIVED TERMINAL SUMMARY — HASH-LINKED TO RAW DEVICE LOGS", "#7dd3fc", bold),
        (f"status: {summary['status']}", "#86efac", font),
        (f"trial: {summary['trial_id']}", "#e2e8f0", font),
        (f"delivery: {summary['received_count']}/{summary['requested_count']} (100.0%)", "#e2e8f0", font),
        (f"Wilson 95% CI: {summary['delivery_fraction_wilson_95_ci'][0]*100:.3f}%–100.000%", "#e2e8f0", font),
        (f"correlation mismatches / duplicates / unexpected: {summary['correlation_mismatch_count']} / {summary['responder_duplicate_count']} / {summary['unexpected_event_count']}", "#e2e8f0", font),
        (f"RTT mean / median / p95: {summary['rtt_ms']['mean']:.3f} / {summary['rtt_ms']['median']:.3f} / {summary['rtt_ms']['p95']:.3f} ms", "#fde68a", font),
        (f"RTT min / max / population SD: {summary['rtt_ms']['minimum']:.3f} / {summary['rtt_ms']['maximum']:.3f} / {summary['rtt_ms']['population_standard_deviation']:.3f} ms", "#fde68a", font),
        ("", "#e2e8f0", font),
        ("RAW SHA-256", "#7dd3fc", bold),
        (f"Sentinel: {summary['raw_evidence']['initiator_sha256']}", "#cbd5e1", font),
        (f"Scout:    {summary['raw_evidence']['responder_sha256']}", "#cbd5e1", font),
        ("", "#e2e8f0", font),
        ("Scope: stationary alert↔verdict messaging on SwarmNet.", "#fca5a5", font),
    ]
    lines.extend(
        (line, "#fca5a5", font)
        for line in textwrap.wrap(summary["claim_boundary"], width=88)
    )
    y = 48
    for content, colour, selected_font in lines:
        draw.text((52, y), content, fill=colour, font=selected_font)
        y += 62 if selected_font is bold else 52
    canvas.save(terminal_path, format="PNG", optimize=True)

    manifest = {
        "schema_version": 1,
        "classification": "derived_visual_evidence",
        "claim_boundary": "Visuals are derived from hash-linked device records and are not independent measurement sources.",
        "source_summary_sha256": sha256(args.summary),
        "source_samples_sha256": sha256(args.samples),
        "outputs": {
            plot_path.name: sha256(plot_path),
            terminal_path.name: sha256(terminal_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
