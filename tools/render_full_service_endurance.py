#!/usr/bin/env python3
"""Render thesis-ready figures for the 29 September full-service run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def elapsed_minutes(records):
    start = float(records[0]["monotonic_seconds"])
    return np.array([(float(row["monotonic_seconds"]) - start) / 60.0 for row in records])


def temperatures(records):
    values = []
    for row in records:
        valid = [
            float(zone.get("celsius_if_millidegrees", 0.0))
            for zone in row.get("thermal_zones", [])
            if 1.0 <= float(zone.get("celsius_if_millidegrees", 0.0)) < 120.0
        ]
        values.append(max(valid) if valid else np.nan)
    return np.array(values)


def resource_series(records):
    def number(value, scale=1.0):
        return np.nan if value is None else float(value) / scale

    return {
        "minutes": elapsed_minutes(records),
        "cpu": np.array([number(r.get("cpu_total_percent")) for r in records]),
        "memory": np.array([number(r.get("mem_available_kib"), 1024.0) for r in records]),
        "swap": np.array([
            (float(r.get("swap_total_kib", 0.0)) - float(r.get("swap_free_kib", 0.0))) / 1024.0
            for r in records
        ]),
        "temperature": temperatures(records),
    }


def style():
    plt.rcParams.update({
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "legend.fontsize": 8,
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "axes.grid": True,
        "grid.alpha": 0.25,
    })


def render_resources(sentinel, scout, output):
    colors = {"Sentinel": "#d95f02", "Scout": "#1f78b4"}
    series = {"Sentinel": resource_series(sentinel), "Scout": resource_series(scout)}
    fig, axes = plt.subplots(2, 2, figsize=(10.0, 6.6), constrained_layout=True)
    specs = [
        ("cpu", "Host CPU utilization (%)"),
        ("memory", "Available memory (MiB)"),
        ("temperature", "Maximum valid thermal-zone reading (°C)"),
        ("swap", "Swap used (MiB)"),
    ]
    for axis, (metric, label) in zip(axes.flat, specs):
        for device, values in series.items():
            axis.plot(values["minutes"], values[metric], color=colors[device], linewidth=1.0, label=device)
        axis.set_xlabel("Elapsed host-resource observation (min)")
        axis.set_ylabel(label)
        axis.set_xlim(left=0)
    axes[0, 0].legend(loc="best", frameon=True)
    fig.suptitle(
        "Stationary complete-service host resources (29 September 2026)\n"
        "Live cameras, edge inference, ROS 2, logging, SwarmNet and PX4/MAVLink services",
        fontsize=11,
    )
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def ecdf(values):
    ordered = np.sort(np.asarray(values, dtype=float))
    return ordered, np.arange(1, len(ordered) + 1) / len(ordered)


def render_latency(sentinel_events, scout_events, probe_events, output):
    sentinel = [r["inference_latency_ms"] for r in sentinel_events if r.get("event_type") == "inference"]
    scout = [r["inference_latency_ms"] for r in scout_events if r.get("event_type") == "verification_inference"]
    end_to_end = [r["latency_ms"] for r in probe_events if r.get("received")]
    fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.2), constrained_layout=True)
    for values, label, color in (
        (sentinel, f"Sentinel TensorRT inference (n={len(sentinel):,})", "#d95f02"),
        (scout, f"Scout TFLite inference (n={len(scout)})", "#1f78b4"),
        (end_to_end, f"Synthetic alert-to-verdict (n={len(end_to_end)})", "#33a02c"),
    ):
        x, y = ecdf(values)
        axes[0].plot(x, y, linewidth=1.5, label=label, color=color)
    axes[0].set_xlabel("Latency (ms; logarithmic scale)")
    axes[0].set_ylabel("Empirical cumulative probability")
    axes[0].set_xscale("log")
    axes[0].set_ylim(0, 1.01)
    axes[0].legend(loc="lower right")
    axes[0].set_title("Latency distributions")

    labels = ["Sentinel\ninference", "Scout\ninference", "Alert-to-\nverdict"]
    data = [sentinel, scout, end_to_end]
    boxes = axes[1].boxplot(data, tick_labels=labels, showfliers=True, patch_artist=True)
    for patch, color in zip(boxes["boxes"], ("#fdbf6f", "#a6cee3", "#b2df8a")):
        patch.set_facecolor(color)
    axes[1].axhline(200.0, color="#d95f02", linestyle="--", linewidth=1.0, label="Sentinel target: 200 ms")
    axes[1].axhline(2000.0, color="#1f78b4", linestyle="--", linewidth=1.0, label="Scout target: 2,000 ms")
    axes[1].set_yscale("log")
    axes[1].set_ylabel("Latency (ms; logarithmic scale)")
    axes[1].set_title("Distribution and preregistered limits")
    axes[1].legend(loc="upper left")
    fig.suptitle(
        "Complete-service latency evidence\n"
        "Alert-to-verdict excludes Sentinel detection and covers the corrected final three-minute probe",
        fontsize=11,
    )
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sentinel-resources", type=Path, required=True)
    parser.add_argument("--scout-resources", type=Path, required=True)
    parser.add_argument("--sentinel-events", type=Path, required=True)
    parser.add_argument("--scout-events", type=Path, required=True)
    parser.add_argument("--probe-events", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    style()
    render_resources(
        read_jsonl(args.sentinel_resources),
        read_jsonl(args.scout_resources),
        args.output_directory / "full_service_resource_timeseries.png",
    )
    render_latency(
        read_jsonl(args.sentinel_events),
        read_jsonl(args.scout_events),
        read_jsonl(args.probe_events),
        args.output_directory / "full_service_latency_distributions.png",
    )
    for path in sorted(args.output_directory.glob("*.png")):
        print(path)


if __name__ == "__main__":
    main()
