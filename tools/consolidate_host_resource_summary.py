#!/usr/bin/env python3
"""Create a thesis-facing host-resource summary from frozen validation runs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


FIELDS = (
    "model_id",
    "canonical_evidence_id",
    "sampling_interval_seconds",
    "duration_seconds",
    "sample_count",
    "system_cpu_mean_percent",
    "system_ram_mean_mib",
    "system_ram_max_mib",
    "gpu_utilization_mean_percent",
    "gpu_memory_max_mib",
    "gpu_power_mean_w",
    "gpu_temperature_max_c",
    "run_summary_sha256",
    "resource_samples_sha256",
)

DISPLAY_NAMES = {
    "yolov8n_416": "YOLOv8n-416",
    "yolov8n_640": "YOLOv8n-640",
    "yolov8s_416": "YOLOv8s-416",
    "yolov8s_640": "YOLOv8s-640",
    "ssd_mobilenet_v2_fpnlite_320": "SSD MobileNet-320",
    "efficientdet_lite0_320": "EfficientDet-320",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_text_lf(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def load_comparison(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 6:
        raise ValueError(f"expected six frozen validation rows, found {len(rows)}")
    return rows


def metric(summary: dict, name: str, statistic: str) -> float:
    try:
        return float(summary["metrics"][name][statistic])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"missing {name}.{statistic}") from error


def consolidate(comparison: Path, resources: Path) -> tuple[list[dict], list[dict]]:
    output_rows: list[dict] = []
    inputs: list[dict] = []
    for row in load_comparison(comparison):
        evidence_id = row["canonical_evidence_id"]
        summary_path = resources / evidence_id / "run_summary.json"
        if not summary_path.is_file():
            raise FileNotFoundError(summary_path)
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("status") != "completed" or summary.get("return_code") != 0:
            raise ValueError(f"resource run is not completed: {evidence_id}")
        if summary.get("model_id") != row["model_id"]:
            raise ValueError(f"model mismatch for {evidence_id}")
        output_rows.append(
            {
                "model_id": row["model_id"],
                "canonical_evidence_id": evidence_id,
                "sampling_interval_seconds": float(summary["sampling_interval_seconds"]),
                "duration_seconds": float(summary["duration_seconds"]),
                "sample_count": int(summary["sample_count"]),
                "system_cpu_mean_percent": metric(summary, "system_cpu_percent", "mean"),
                "system_ram_mean_mib": metric(summary, "system_ram_used_mib", "mean"),
                "system_ram_max_mib": metric(summary, "system_ram_used_mib", "maximum"),
                "gpu_utilization_mean_percent": metric(
                    summary, "gpu_utilization_percent", "mean"
                ),
                "gpu_memory_max_mib": metric(summary, "gpu_memory_used_mib", "maximum"),
                "gpu_power_mean_w": metric(summary, "gpu_power_w", "mean"),
                "gpu_temperature_max_c": metric(summary, "gpu_temperature_c", "maximum"),
                "run_summary_sha256": sha256(summary_path),
                "resource_samples_sha256": summary["evidence"]["resource_samples_sha256"],
            }
        )
        inputs.append(
            {
                "model_id": row["model_id"],
                "canonical_evidence_id": evidence_id,
                "run_summary_path": summary_path,
                "run_summary_sha256": sha256(summary_path),
            }
        )
    return output_rows, inputs


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--comparison-csv",
        type=Path,
        default=repo
        / "artifacts/experiments/model_screening_v1/validation_comparison_v1/"
        "consolidated_20260809/validation_model_comparison.csv",
    )
    parser.add_argument(
        "--resources-directory",
        type=Path,
        default=repo
        / "artifacts/experiments/model_screening_v1/validation_comparison_v1/resources",
    )
    parser.add_argument("--output-directory", type=Path, default=repo / "thesis/generated")
    args = parser.parse_args()

    comparison = args.comparison_csv.resolve()
    resources = args.resources_directory.resolve()
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows, inputs = consolidate(comparison, resources)

    csv_path = output / "host_resource_summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    tex_path = output / "host_resource_summary_rows.tex"
    tex_rows = []
    for row in rows:
        tex_rows.append(
            f"    {DISPLAY_NAMES[row['model_id']]} & {row['sample_count']:,} & "
            f"{row['duration_seconds']:.3f} & {row['system_cpu_mean_percent']:.2f} & "
            f"{row['system_ram_mean_mib']:,.1f} & "
            f"{row['gpu_utilization_mean_percent']:.2f} & "
            f"{row['gpu_memory_max_mib']:,.0f} & {row['gpu_power_mean_w']:.2f} & "
            f"{row['gpu_temperature_max_c']:.0f} \\\\%"
        )
    write_text_lf(
        tex_path,
        "\\newcommand{\\HostResourceRows}{%\n"
        + "\n".join(tex_rows)
        + "\n}\n",
    )

    manifest = {
        "schema_version": 1,
        "status": "derived_from_frozen_validation_resource_runs",
        "comparison_csv_sha256": sha256(comparison),
        "sampling_boundary": (
            "host-wide CPU/RAM and device-wide NVIDIA GPU observations; "
            "durations and sample counts differ by runtime"
        ),
        "inputs": [
            {
                **{key: value for key, value in item.items() if key != "run_summary_path"},
                "run_summary": item["run_summary_path"]
                .resolve()
                .relative_to(repo)
                .as_posix(),
            }
            for item in inputs
        ],
        "outputs": [
            {
                "path": path.relative_to(repo).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in (csv_path, tex_path)
        ],
        "limitations": [
            "Host CPU and RAM include the operating system and other background work.",
            "NVIDIA samples are device-wide and may include display activity.",
            "WSL process RSS may be under-reported, so system RAM is retained instead.",
            "Different run durations and sample counts prevent a controlled energy comparison.",
        ],
    }
    manifest_path = output / "host_resource_summary_manifest.json"
    write_text_lf(
        manifest_path,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
