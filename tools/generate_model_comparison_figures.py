#!/usr/bin/env python3
"""Generate thesis figures from frozen validation and one-time test summaries."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / "artifacts" / "envs" / "matplotlib_config"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


SHORT = {
    "yolov8n_416": "v8n-416",
    "yolov8n_640": "v8n-640",
    "yolov8s_416": "v8s-416",
    "yolov8s_640": "v8s-640",
    "ssd_mobilenet_v2_fpnlite_320": "SSD-320",
    "efficientdet_lite0_320": "EffDet-320",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def save(fig, stem: Path) -> list[Path]:
    outputs = []
    for extension in ("pdf", "png"):
        path = stem.with_suffix("." + extension)
        fig.savefig(path, dpi=300, bbox_inches="tight")
        outputs.append(path)
    plt.close(fig)
    return outputs


def grouped_metric_plot(validation, test, key: str, ylabel: str, stem: Path):
    ids = [row["model_id"] for row in validation]
    test_by_id = {row["model_id"]: row for row in test}
    x = np.arange(len(ids))
    width = 0.36
    validation_values = [float(row[key]) for row in validation]
    test_values = [float(test_by_id[model_id][key]) for model_id in ids]
    fig, ax = plt.subplots(figsize=(9.2, 4.8))
    first = ax.bar(x - width / 2, validation_values, width, label="Validation", color="#4472C4")
    second = ax.bar(x + width / 2, test_values, width, label="Untouched test", color="#ED7D31")
    ax.set_ylabel(ylabel)
    ax.set_xticks(x, [SHORT[model_id] for model_id in ids])
    ax.set_ylim(0, max(validation_values + test_values) * 1.22)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(frameon=False, ncol=2, loc="upper right")
    ax.bar_label(first, fmt="%.3f", padding=2, fontsize=8)
    ax.bar_label(second, fmt="%.3f", padding=2, fontsize=8)
    fig.tight_layout()
    return save(fig, stem)


def pareto_plot(validation, stem: Path):
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    for row in validation:
        model_id = row["model_id"]
        x = float(row["latency_mean_ms"])
        y = float(row["ap50_95"])
        pareto = row["exploratory_ap_latency_pareto"].lower() == "true"
        cpu = row["runtime_device"].startswith("CPU")
        ax.scatter(
            x,
            y,
            marker="s" if cpu else "o",
            s=75 if pareto else 52,
            facecolor="#4472C4" if pareto else "#A5A5A5",
            edgecolor="#1F1F1F",
            linewidth=0.8,
            zorder=3,
        )
        label = SHORT[model_id]
        offset = (6, 7) if model_id != "efficientdet_lite0_320" else (-4, 7)
        ax.annotate(label, (x, y), xytext=offset, textcoords="offset points", fontsize=8,
                    ha="right" if model_id == "efficientdet_lite0_320" else "left")
    ax.set_xscale("log")
    ax.set_xlabel("Mean single-image inference latency (ms, logarithmic scale)")
    ax.set_ylabel("Validation AP50–95")
    ax.grid(True, which="both", alpha=0.25)
    fig.tight_layout()
    return save(fig, stem)


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--validation-csv", type=Path, required=True)
    parser.add_argument("--test-csv", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=True)
    validation = rows(args.validation_csv.resolve())
    test = rows(args.test_csv.resolve())
    if len(validation) != 6 or len(test) != 6:
        raise ValueError("expected six validation and six test rows")

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )
    generated = []
    generated += grouped_metric_plot(
        validation, test, "ap50_95", "AP50–95", output / "model_ap_validation_test"
    )
    generated += grouped_metric_plot(
        validation, test, "f1", "F1 at frozen validation threshold", output / "model_f1_validation_test"
    )
    generated += pareto_plot(validation, output / "validation_ap_latency_pareto")
    manifest = {
        "schema_version": 1,
        "validation_csv_sha256": sha256(args.validation_csv.resolve()),
        "test_csv_sha256": sha256(args.test_csv.resolve()),
        "files": [
            {
                "path": path.resolve().relative_to(repo).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in generated
        ],
    }
    manifest_path = output / "model_comparison_figure_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
