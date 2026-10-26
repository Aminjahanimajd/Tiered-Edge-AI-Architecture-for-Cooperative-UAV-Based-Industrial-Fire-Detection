#!/usr/bin/env python3
"""Verify and summarize the successful Scout exact-device screening runs.

The script deliberately keeps the original failed YOLO attempts in the evidence
lineage while selecting only the scientifically valid recovery runs for numeric
comparison.  It never mutates raw device output.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any


EXPECTED = {
    "efficientdet_lite0_320": {
        "relative": Path("exact_device_screening_20260925_r1/efficientdet_lite0_320"),
        "model_sha256": "948e71fa53fa9a740a2bca45f169280a9c6e6596a49bfcab65d0ad9cfda2f12c",
        "lineage": "initial formal run; completed before YOLO decoder defect",
    },
    "yolov8n_416": {
        "relative": Path("exact_device_screening_20260925_r2_yolo_recovery/yolov8n_416"),
        "model_sha256": "aefbc333350898a1be0e7c7e1fe1038722fbecb00ddc5b25f5d5f599ff473a80",
        "lineage": "recovery run after fire-only decoder class-count correction",
    },
    "yolov8s_416": {
        "relative": Path("exact_device_screening_20260925_r2_yolo_recovery/yolov8s_416"),
        "model_sha256": "ef2fbce918f2109caa072f6aac30a49334ba68529ddec7cca21d2379f4e3e207",
        "lineage": "recovery run after fire-only decoder class-count correction",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: list[float], percentage: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentage / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def describe(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
        "p95": percentile(values, 95.0),
        "population_standard_deviation": statistics.pstdev(values),
    }


def parse_kib(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().split()
    if not text:
        return None
    return float(text[0])


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
    return records


def collect_failure_history(root: Path) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    original = root / "exact_device_screening_20260925_r1"
    for model_id in ("yolov8n_416", "yolov8s_416"):
        path = original / model_id / "run_summary.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("status") != "FAIL":
            raise ValueError(f"expected retained pre-fix failure for {model_id}")
        failures.append(
            {
                "model_id": model_id,
                "status": record["status"],
                "error": record.get("error"),
                "summary_path": str(path.resolve()),
                "summary_sha256": sha256(path),
            }
        )
    return failures


def analyze_run(model_id: str, root: Path, specification: dict[str, Any]) -> dict[str, Any]:
    run = root / specification["relative"]
    summary_path = run / "run_summary.json"
    latency_path = run / "latency_samples.csv"
    resource_path = run / "resource_samples.jsonl"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("status") != "PASS" or summary.get("model_id") != model_id:
        raise ValueError(f"invalid selected run for {model_id}")
    if summary["model"]["sha256"] != specification["model_sha256"]:
        raise ValueError(f"model hash mismatch for {model_id}")
    if sha256(latency_path) != summary["latency_samples_sha256"]:
        raise ValueError(f"latency hash mismatch for {model_id}")
    if sha256(resource_path) != summary["resource_samples_sha256"]:
        raise ValueError(f"resource hash mismatch for {model_id}")

    with latency_path.open(newline="", encoding="utf-8") as source:
        latency_rows = list(csv.DictReader(source))
    if len(latency_rows) != summary["latency_sample_count"] or len(latency_rows) != 200:
        raise ValueError(f"unexpected latency sample count for {model_id}")
    indices = [int(row["iteration_index"]) for row in latency_rows]
    if indices != list(range(200)):
        raise ValueError(f"non-contiguous iteration sequence for {model_id}")

    resources = read_jsonl(resource_path)
    if len(resources) != summary["resource_sample_count"]:
        raise ValueError(f"resource sample count mismatch for {model_id}")
    cpu = [float(row["cpu_total_percent"]) for row in resources if row.get("cpu_total_percent") is not None]
    mem_available = [value for row in resources if (value := parse_kib(row.get("mem_available"))) is not None]
    process_rss = [value for row in resources if (value := parse_kib(row.get("process_vm_rss"))) is not None]
    process_hwm = [value for row in resources if (value := parse_kib(row.get("process_vm_hwm"))) is not None]
    swap_used = []
    thermal = []
    for row in resources:
        total = parse_kib(row.get("swap_total"))
        free = parse_kib(row.get("swap_free"))
        if total is not None and free is not None:
            swap_used.append(total - free)
        for zone in row.get("thermal_zones", []):
            value = zone.get("celsius_if_millidegrees")
            if value is not None and 0.0 < float(value) < 120.0:
                thermal.append(float(value))

    duration_seconds = (summary["finished_monotonic_ns"] - summary["started_monotonic_ns"]) / 1e9
    fields = ("load_decode_ms", "preprocess_ms", "inference_ms", "postprocess_ms", "pipeline_ms")
    latencies = {field: describe([float(row[field]) for row in latency_rows]) for field in fields}
    return {
        "model_id": model_id,
        "status": "PASS",
        "selected_run_lineage": specification["lineage"],
        "backend": summary["backend"],
        "runtime": summary["runtime"],
        "model_sha256": summary["model"]["sha256"],
        "model_bytes": summary["model"]["bytes"],
        "model_mebibytes": summary["model"]["bytes"] / (1024 * 1024),
        "input": summary["model_input"],
        "calibration_manifest_sha256": summary["calibration"]["manifest_sha256"],
        "verified_replay_image_count": summary["calibration"]["verified_image_count"],
        "warmup_inferences": summary["parameters"]["warmup_inferences"],
        "measured_inferences": summary["parameters"]["measured_inferences"],
        "duration_seconds": duration_seconds,
        "latency_ms": latencies,
        "derived_throughput_fps_from_mean_pipeline": 1000.0 / float(latencies["pipeline_ms"]["mean"]),
        "resources": {
            "sampling_interval_seconds": summary["parameters"]["resource_interval_seconds"],
            "sample_count": len(resources),
            "cpu_total_percent": describe(cpu),
            "mem_available_mib": describe([value / 1024.0 for value in mem_available]),
            "process_rss_mib": describe([value / 1024.0 for value in process_rss]),
            "process_hwm_mib": describe([value / 1024.0 for value in process_hwm]),
            "swap_used_mib": describe([value / 1024.0 for value in swap_used]),
            "all_valid_thermal_zones_celsius": describe(thermal),
        },
        "raw_evidence": {
            "run_summary_path": str(summary_path.resolve()),
            "run_summary_sha256": sha256(summary_path),
            "latency_samples_path": str(latency_path.resolve()),
            "latency_samples_sha256": sha256(latency_path),
            "resource_samples_path": str(resource_path.resolve()),
            "resource_samples_sha256": sha256(resource_path),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    if args.output_directory.exists():
        parser.error("output directory exists; analysis is non-overwriting")

    runs = [analyze_run(model_id, args.evidence_root, specification) for model_id, specification in EXPECTED.items()]
    calibration_hashes = {run["calibration_manifest_sha256"] for run in runs}
    if len(calibration_hashes) != 1:
        raise ValueError("selected runs do not share a calibration manifest")

    args.output_directory.mkdir(parents=True, exist_ok=False)
    table_path = args.output_directory / "scout_exact_device_comparison.csv"
    with table_path.open("x", newline="", encoding="utf-8") as destination:
        fieldnames = (
            "model_id", "runtime", "provider", "model_mebibytes", "input_size",
            "inference_mean_ms", "inference_median_ms", "inference_p95_ms",
            "pipeline_mean_ms", "pipeline_median_ms", "pipeline_p95_ms",
            "derived_throughput_fps", "cpu_mean_percent", "cpu_max_percent",
            "process_rss_max_mib", "mem_available_min_mib", "max_valid_temperature_celsius",
            "latency_n", "resource_n",
        )
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        writer.writeheader()
        for run in runs:
            resources = run["resources"]
            writer.writerow(
                {
                    "model_id": run["model_id"],
                    "runtime": run["runtime"]["name"],
                    "provider": ";".join(run["runtime"].get("providers", [])) or "runtime_default_cpu_delegate_unspecified",
                    "model_mebibytes": run["model_mebibytes"],
                    "input_size": f"{run['input']['width']}x{run['input']['height']}",
                    "inference_mean_ms": run["latency_ms"]["inference_ms"]["mean"],
                    "inference_median_ms": run["latency_ms"]["inference_ms"]["median"],
                    "inference_p95_ms": run["latency_ms"]["inference_ms"]["p95"],
                    "pipeline_mean_ms": run["latency_ms"]["pipeline_ms"]["mean"],
                    "pipeline_median_ms": run["latency_ms"]["pipeline_ms"]["median"],
                    "pipeline_p95_ms": run["latency_ms"]["pipeline_ms"]["p95"],
                    "derived_throughput_fps": run["derived_throughput_fps_from_mean_pipeline"],
                    "cpu_mean_percent": resources["cpu_total_percent"].get("mean"),
                    "cpu_max_percent": resources["cpu_total_percent"].get("maximum"),
                    "process_rss_max_mib": resources["process_rss_mib"].get("maximum"),
                    "mem_available_min_mib": resources["mem_available_mib"].get("minimum"),
                    "max_valid_temperature_celsius": resources["all_valid_thermal_zones_celsius"].get("maximum"),
                    "latency_n": run["latency_ms"]["pipeline_ms"]["n"],
                    "resource_n": resources["sample_count"],
                }
            )

    summary = {
        "schema_version": 1,
        "status": "PASS",
        "platform": "Scout / VOXL 2",
        "experiment_type": "exact-device camera-free replay screening",
        "selected_run_rule": "latest valid PASS per candidate; completed EfficientDet retained from R1; only failed YOLO candidates recovered in R2",
        "shared_calibration_manifest_sha256": next(iter(calibration_hashes)),
        "runs": runs,
        "retained_pre_fix_failures": collect_failure_history(args.evidence_root),
        "claim_boundary": (
            "The comparison measures camera-free replay latency and sampled resources on the Scout. "
            "It does not establish predictive accuracy, live-camera endurance, flight behavior, or industrial reliability."
        ),
        "resource_limitations": (
            "Resource sampling occurred at 1 Hz and produced unequal sample counts because candidate runtimes differed. "
            "The runtime-reported CPU provider/delegate labels are retained exactly; GPU/NPU acceleration is not inferred."
        ),
        "derived_evidence": {
            "comparison_csv": table_path.name,
            "comparison_csv_sha256": sha256(table_path),
        },
    }
    summary_path = args.output_directory / "scout_exact_device_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
