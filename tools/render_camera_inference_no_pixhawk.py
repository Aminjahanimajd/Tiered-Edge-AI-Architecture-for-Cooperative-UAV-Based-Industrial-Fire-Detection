#!/usr/bin/env python3
"""Render thesis-ready visual evidence for the no-Pixhawk camera baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def elapsed(records: list[dict[str, Any]]) -> list[float]:
    if not records:
        return []
    start = float(records[0]["monotonic_seconds"])
    return [float(record["monotonic_seconds"]) - start for record in records]


def maximum_temperature(record: dict[str, Any]) -> float | None:
    values = [
        float(zone["celsius_if_millidegrees"])
        for zone in record.get("thermal_zones", [])
        if 0.0 < float(zone.get("celsius_if_millidegrees", 0.0)) < 120.0
    ]
    return max(values) if values else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--probe-events", type=Path, required=True)
    parser.add_argument("--sentinel-resources", type=Path, required=True)
    parser.add_argument("--scout-resources", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()

    analysis = read_json(args.analysis)
    probe = read_jsonl(args.probe_events)
    sentinel = read_jsonl(args.sentinel_resources)
    scout = read_jsonl(args.scout_resources)
    args.output_directory.mkdir(parents=True, exist_ok=True)

    figure_path = args.output_directory / "camera_inference_no_pixhawk_timeseries.png"
    terminal_path = args.output_directory / "camera_inference_no_pixhawk_terminal_summary.png"
    manifest_path = args.output_directory / "visual_manifest.json"

    plt.rcParams.update({"font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9})
    fig, axes = plt.subplots(2, 2, figsize=(11.2, 7.4), constrained_layout=True)
    fig.suptitle(
        "Stationary camera and edge-inference baseline (Sentinel Pixhawk unpowered)",
        fontsize=13,
        fontweight="bold",
    )

    sequences = [int(record["sequence"]) for record in probe]
    latencies = [float(record["latency_ms"]) for record in probe if record.get("received")]
    axes[0, 0].plot(sequences[: len(latencies)], latencies, color="#1565c0", linewidth=1.1)
    axes[0, 0].axhline(2000.0, color="#c62828", linestyle="--", linewidth=1.0, label="2 s target")
    axes[0, 0].set(title=f"Alert-to-Scout-verdict latency (n={len(latencies)})", xlabel="Request sequence", ylabel="Latency (ms)")
    axes[0, 0].grid(alpha=0.25)
    axes[0, 0].legend(loc="best")

    for records, label, color in ((sentinel, "Sentinel", "#ef6c00"), (scout, "Scout", "#2e7d32")):
        times = elapsed(records)
        axes[0, 1].plot(times, [record.get("cpu_total_percent") for record in records], label=label, color=color, linewidth=1.0)
        axes[1, 0].plot(times, [float(record["mem_available_kib"]) / 1024.0 for record in records], label=label, color=color, linewidth=1.0)
        temps = [maximum_temperature(record) for record in records]
        axes[1, 1].plot(times, temps, label=label, color=color, linewidth=1.0)

    axes[0, 1].set(title="Host-wide CPU utilization", xlabel="Elapsed time (s)", ylabel="CPU (%)")
    axes[1, 0].set(title="Available memory", xlabel="Elapsed time (s)", ylabel="MemAvailable (MiB)")
    axes[1, 1].set(title="Maximum reported thermal-zone temperature", xlabel="Elapsed time (s)", ylabel="Temperature (°C)")
    for axis in (axes[0, 1], axes[1, 0], axes[1, 1]):
        axis.grid(alpha=0.25)
        axis.legend(loc="best")
    fig.text(
        0.5,
        -0.01,
        "Scope: live cameras, edge inference, ROS 2 transport and 1 Hz host resources; no Pixhawk, flight, power, accuracy or industrial-reliability claim.",
        ha="center",
        fontsize=8,
    )
    fig.savefig(figure_path, dpi=180, bbox_inches="tight")
    plt.close(fig)

    probe_summary = analysis["probe"]
    scout_summary = analysis["scout"]
    sentinel_summary = analysis["sentinel"]
    lines = [
        "CAMERA + INFERENCE BASELINE — NO SENTINEL PIXHAWK",
        f"Trial: {analysis['trial_id']}",
        "",
        f"Probe: {probe_summary['received_count']}/{probe_summary['requested_count']} verdicts received",
        f"Missing / mismatched / duplicate: {probe_summary['missing_count']} / {probe_summary['correlation_mismatch_count']} / {probe_summary['duplicate_count']}",
        f"Alert-to-verdict p95: {probe_summary['latency_ms']['p95']:.3f} ms",
        f"Scout stale-frame / error verdicts: {scout_summary['stale_frame_verdicts']} / {scout_summary['error_verdicts']}",
        f"Scout inference p95: {scout_summary['inference_latency_ms']['p95']:.3f} ms",
        f"Sentinel inference frames: {sentinel_summary['inference_frames']}",
        f"Sentinel inference p95: {sentinel_summary['inference_latency_ms']['p95']:.3f} ms",
        "",
        f"Sentinel resource samples: {sentinel_summary['resources']['sample_count']}",
        f"Sentinel minimum MemAvailable: {sentinel_summary['resources']['mem_available_mib']['minimum']:.1f} MiB",
        f"Scout resource samples: {scout_summary['resources']['sample_count']}",
        f"Scout minimum MemAvailable: {scout_summary['resources']['mem_available_mib']['minimum']:.1f} MiB",
        f"Node exit codes (Sentinel / Scout): {sentinel_summary['node_exit_code']} / {scout_summary['node_exit_code']}",
        "",
        "Interpretation: measured stationary coexistence evidence.",
        "Limitation: no Pixhawk, motors, navigation, power meter, or flight.",
    ]
    terminal_fig = plt.figure(figsize=(12, 6.6), facecolor="#111318")
    terminal_fig.text(0.045, 0.95, "\n".join(lines), va="top", ha="left", color="#e8eaed", family="monospace", fontsize=11, linespacing=1.35)
    terminal_fig.savefig(terminal_path, dpi=170, facecolor=terminal_fig.get_facecolor(), bbox_inches="tight")
    plt.close(terminal_fig)

    manifest = {
        "schema_version": 1,
        "trial_id": analysis["trial_id"],
        "inputs": {
            "analysis": {"path": str(args.analysis.resolve()), "sha256": sha256(args.analysis)},
            "probe_events": {"path": str(args.probe_events.resolve()), "sha256": sha256(args.probe_events)},
            "sentinel_resources": {"path": str(args.sentinel_resources.resolve()), "sha256": sha256(args.sentinel_resources)},
            "scout_resources": {"path": str(args.scout_resources.resolve()), "sha256": sha256(args.scout_resources)},
        },
        "outputs": {
            figure_path.name: sha256(figure_path),
            terminal_path.name: sha256(terminal_path),
        },
        "claim_boundary": analysis["claim_boundary"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
