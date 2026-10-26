#!/usr/bin/env python3
"""Generate exact-backend and ROS round-trip latency distribution figure."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib.pyplot as plt
import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_backend(path: Path) -> dict[str, list[float]]:
    values: dict[str, list[float]] = {"sentinel": [], "scout": []}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            values[row["device"]].append(float(row["pipeline_ms"]))
    return values


def read_rtt(path: Path) -> list[float]:
    with path.open(newline="", encoding="utf-8") as stream:
        return [
            float(row["round_trip_ms"])
            for row in csv.DictReader(stream)
            if row["received"].lower() == "true" and row["correlation_match"].lower() == "true"
        ]


def summary(values: list[float]) -> dict[str, float | int]:
    data = np.asarray(values, dtype=float)
    return {
        "n": int(data.size),
        "mean_ms": float(data.mean()),
        "median_ms": float(np.median(data)),
        "minimum_ms": float(data.min()),
        "maximum_ms": float(data.max()),
        "standard_deviation_ms": float(data.std(ddof=1)),
        "p95_ms": float(np.percentile(data, 95)),
    }


def draw_ecdf(axis: plt.Axes, values: list[float], title: str, color: str) -> dict:
    data = np.sort(np.asarray(values, dtype=float))
    probability = np.arange(1, data.size + 1) / data.size
    stats = summary(values)
    axis.step(data, probability, where="post", color=color, linewidth=2.0)
    axis.axvline(stats["median_ms"], color="black", linestyle="--", linewidth=1.0, label="Median")
    axis.axvline(stats["p95_ms"], color="black", linestyle=":", linewidth=1.2, label="95th percentile")
    axis.set_title(title)
    axis.set_xlabel("Latency (ms)")
    axis.set_xlim(left=0.0)
    axis.set_ylim(0.0, 1.02)
    axis.grid(alpha=0.25)
    axis.text(
        0.04,
        0.95,
        f"n={stats['n']}\nmean={stats['mean_ms']:.3f} ms\n"
        f"median={stats['median_ms']:.3f} ms\np95={stats['p95_ms']:.3f} ms",
        transform=axis.transAxes,
        va="top",
        fontsize=8.5,
        bbox={"facecolor": "white", "edgecolor": "0.75", "alpha": 0.9},
    )
    return stats


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    derived = repo / "artifacts/experiments/hardware_lab_20260803/derived"
    backend_csv = derived / "backend_comparison_r1/benchmark_samples.csv"
    rtt_csv = derived / "ros_roundtrip_analysis/ros_roundtrip_samples.csv"
    output = repo / "thesis/generated"
    output.mkdir(parents=True, exist_ok=True)

    backend = read_backend(backend_csv)
    rtt = read_rtt(rtt_csv)
    if len(backend["sentinel"]) != 100 or len(backend["scout"]) != 100 or len(rtt) != 300:
        raise ValueError("unexpected retained sample count")

    figure, axes = plt.subplots(1, 3, figsize=(11.2, 3.9), sharey=True)
    summaries = {
        "sentinel_backend_pipeline": draw_ecdf(
            axes[0], backend["sentinel"], "Sentinel backend pipeline", "#4472C4"
        ),
        "scout_backend_pipeline": draw_ecdf(
            axes[1], backend["scout"], "Scout backend pipeline", "#ED7D31"
        ),
        "ros_round_trip": draw_ecdf(
            axes[2], rtt, "ROS 2/DDS request–reply", "#70AD47"
        ),
    }
    axes[0].set_ylabel("Empirical cumulative probability")
    handles, labels = axes[2].get_legend_handles_labels()
    figure.legend(handles, labels, loc="lower center", ncol=2, frameon=False)
    figure.subplots_adjust(bottom=0.22, wspace=0.13)

    outputs = [output / "hardware_latency_ecdf.pdf", output / "hardware_latency_ecdf.png"]
    figure.savefig(outputs[0], bbox_inches="tight")
    figure.savefig(outputs[1], dpi=220, bbox_inches="tight")
    plt.close(figure)

    manifest = {
        "schema_version": 1,
        "status": "generated_from_retained_exact_backend_and_correlated_rtt_samples",
        "backend_samples_csv_sha256": sha256(backend_csv),
        "rtt_samples_csv_sha256": sha256(rtt_csv),
        "summaries": summaries,
        "files": [
            {
                "path": path.resolve().relative_to(repo).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in outputs
        ],
        "limitations": [
            "Backend panels use different devices, models, and runtimes.",
            "Backend pipeline samples include preprocess, inference, and decode but exclude camera capture and end-to-end coordination.",
            "RTT is application-level under stationary SwarmNet conditions, not packet-level network latency.",
        ],
    }
    manifest_path = output / "hardware_latency_figure_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
