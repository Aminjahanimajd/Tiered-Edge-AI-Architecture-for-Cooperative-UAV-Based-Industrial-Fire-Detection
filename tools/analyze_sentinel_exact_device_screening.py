#!/usr/bin/env python3
"""Verify and summarize successful Sentinel TensorRT screening runs."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from analyze_scout_exact_device_screening import describe, parse_kib, read_jsonl, sha256


SELECTED = {
    "yolov8n_416": {
        "relative": Path("exact_device_screening_20260928_r3_n416_benchmark/yolov8n_416"),
        "engine_sha256": "aa546ea6d7a7cc666f6b5a4c6a27974513ccad984b567e99394fff3dfd0020a8",
        "build_log": None,
        "engine_metadata": None,
        "lineage": "25 September completed engine; 28 September benchmark-only recovery after two retained setup failures",
    },
    "yolov8s_416": {
        "relative": Path("exact_device_screening_20260928_r2_recovery/yolov8s_416"),
        "engine_sha256": "46da19a16c69b29ce39a1cb17ed6c275840cd823bfb5ca00be288de6b056a742",
        "build_log": Path("exact_device_screening_20260928_r2_recovery/yolov8s_416_trtexec_build.log"),
        "engine_metadata": Path("exact_device_screening_20260928_r2_recovery/yolov8s_416_engine_metadata.json"),
        "lineage": "28 September rebuild after user-requested interruption on 25 September",
    },
}


def tegrastats(path: Path) -> dict:
    ram_used, swap_used, gpu, temperatures = [], [], [], []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.search(r"RAM (\d+)/(\d+)MB", line)
        if match:
            ram_used.append(float(match.group(1)))
        match = re.search(r"SWAP (\d+)/(\d+)MB", line)
        if match:
            swap_used.append(float(match.group(1)))
        match = re.search(r"GR3D_FREQ (\d+)%", line)
        if match:
            gpu.append(float(match.group(1)))
        for _, value in re.findall(r"([A-Za-z0-9_-]+)@([0-9.]+)C", line):
            temperatures.append(float(value))
    return {
        "line_count": len(path.read_text(encoding="utf-8", errors="replace").splitlines()),
        "ram_used_mib": describe(ram_used),
        "swap_used_mib": describe(swap_used),
        "gpu_frequency_utilization_percent": describe(gpu),
        "reported_temperature_celsius": describe(temperatures),
    }


def analyze(root: Path, model_id: str, spec: dict) -> dict:
    run = root / spec["relative"]
    summary_path = run / "run_summary.json"
    latency_path = run / "latency_samples.csv"
    resource_path = run / "resource_samples.jsonl"
    tegra_path = run / "tegrastats.log"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("status") != "PASS" or summary.get("model_id") != model_id:
        raise ValueError(f"selected run is not PASS for {model_id}")
    if summary["model"]["sha256"] != spec["engine_sha256"]:
        raise ValueError(f"engine hash mismatch for {model_id}")
    for path, field in ((latency_path, "latency_samples_sha256"), (resource_path, "resource_samples_sha256"), (tegra_path, "tegrastats_sha256")):
        if sha256(path) != summary[field]:
            raise ValueError(f"raw evidence hash mismatch for {model_id}: {path.name}")
    with latency_path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    if len(rows) != 200 or [int(row["iteration_index"]) for row in rows] != list(range(200)):
        raise ValueError(f"invalid latency sequence for {model_id}")
    latency = {
        field: describe([float(row[field]) for row in rows])
        for field in ("load_decode_ms", "preprocess_ms", "inference_ms", "postprocess_ms", "pipeline_ms")
    }
    resources = read_jsonl(resource_path)
    cpu = [float(row["cpu_total_percent"]) for row in resources if row.get("cpu_total_percent") is not None]
    mem = [value / 1024 for row in resources if (value := parse_kib(row.get("mem_available"))) is not None]
    rss = [value / 1024 for row in resources if (value := parse_kib(row.get("process_vm_rss"))) is not None]
    temperatures = [
        float(zone["celsius_if_millidegrees"])
        for row in resources for zone in row.get("thermal_zones", [])
        if zone.get("celsius_if_millidegrees") is not None and 0 < float(zone["celsius_if_millidegrees"]) < 120
    ]
    raw = {
        "run_summary": {"path": str(summary_path.resolve()), "sha256": sha256(summary_path)},
        "latency_samples": {"path": str(latency_path.resolve()), "sha256": sha256(latency_path)},
        "resource_samples": {"path": str(resource_path.resolve()), "sha256": sha256(resource_path)},
        "tegrastats": {"path": str(tegra_path.resolve()), "sha256": sha256(tegra_path)},
    }
    if spec["build_log"]:
        build = root / spec["build_log"]
        metadata = root / spec["engine_metadata"]
        raw["trtexec_build"] = {"path": str(build.resolve()), "sha256": sha256(build)}
        raw["engine_metadata"] = {"path": str(metadata.resolve()), "sha256": sha256(metadata)}
    return {
        "model_id": model_id,
        "status": "PASS",
        "lineage": spec["lineage"],
        "engine_sha256": summary["model"]["sha256"],
        "engine_bytes": summary["model"]["bytes"],
        "engine_mebibytes": summary["model"]["bytes"] / (1024 * 1024),
        "runtime": summary["runtime"],
        "input": summary["model_input"],
        "latency_ms": latency,
        "derived_throughput_fps": 1000 / float(latency["pipeline_ms"]["mean"]),
        "duration_seconds": (summary["finished_monotonic_ns"] - summary["started_monotonic_ns"]) / 1e9,
        "resources": {
            "sample_count": len(resources),
            "cpu_total_percent": describe(cpu),
            "mem_available_mib": describe(mem),
            "process_rss_mib": describe(rss),
            "all_valid_thermal_zones_celsius": describe(temperatures),
            "tegrastats": tegrastats(tegra_path),
        },
        "raw_evidence": raw,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    if args.output_directory.exists():
        parser.error("output directory exists; analysis is non-overwriting")
    runs = [analyze(args.evidence_root, model_id, spec) for model_id, spec in SELECTED.items()]
    args.output_directory.mkdir(parents=True)
    table = args.output_directory / "sentinel_exact_device_comparison.csv"
    with table.open("x", newline="", encoding="utf-8") as destination:
        fields = ("model_id", "engine_mebibytes", "inference_mean_ms", "inference_p95_ms", "pipeline_mean_ms", "pipeline_median_ms", "pipeline_p95_ms", "derived_throughput_fps", "cpu_mean_percent", "gpu_mean_percent", "gpu_max_percent", "process_rss_max_mib", "mem_available_min_mib", "max_temperature_celsius", "latency_n", "resource_n")
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        for run in runs:
            resource = run["resources"]
            writer.writerow({
                "model_id": run["model_id"],
                "engine_mebibytes": run["engine_mebibytes"],
                "inference_mean_ms": run["latency_ms"]["inference_ms"]["mean"],
                "inference_p95_ms": run["latency_ms"]["inference_ms"]["p95"],
                "pipeline_mean_ms": run["latency_ms"]["pipeline_ms"]["mean"],
                "pipeline_median_ms": run["latency_ms"]["pipeline_ms"]["median"],
                "pipeline_p95_ms": run["latency_ms"]["pipeline_ms"]["p95"],
                "derived_throughput_fps": run["derived_throughput_fps"],
                "cpu_mean_percent": resource["cpu_total_percent"].get("mean"),
                "gpu_mean_percent": resource["tegrastats"]["gpu_frequency_utilization_percent"].get("mean"),
                "gpu_max_percent": resource["tegrastats"]["gpu_frequency_utilization_percent"].get("maximum"),
                "process_rss_max_mib": resource["process_rss_mib"].get("maximum"),
                "mem_available_min_mib": resource["mem_available_mib"].get("minimum"),
                "max_temperature_celsius": resource["all_valid_thermal_zones_celsius"].get("maximum"),
                "latency_n": run["latency_ms"]["pipeline_ms"]["n"],
                "resource_n": resource["sample_count"],
            })
    failure_paths = [
        args.evidence_root / "exact_device_screening_20260928_r2_recovery/yolov8n_416/run_summary.json",
    ]
    failures = [{"path": str(path.resolve()), "sha256": sha256(path), "status": json.loads(path.read_text(encoding="utf-8"))["status"], "error": json.loads(path.read_text(encoding="utf-8")).get("error")} for path in failure_paths]
    summary = {
        "schema_version": 1,
        "status": "PASS",
        "platform": "Sentinel / Jetson Nano 4 GB",
        "experiment_type": "exact-device camera-free replay screening",
        "runs": runs,
        "retained_recovery_failures_in_current_bundle": failures,
        "additional_retained_failure": "25 September YOLOv8n decoder/setup failure and interrupted YOLOv8s build are preserved in the prior checkpoint bundle.",
        "claim_boundary": "TensorRT FP16 camera-free replay latency/resources only; not predictive accuracy, camera endurance, flight, or industrial reliability.",
        "resource_limitations": "Resource sampling was 1 Hz and run durations differ. Tegrastats GR3D_FREQ is a utilization/frequency indicator, not electrical power or energy.",
        "derived_evidence": {"comparison_csv": table.name, "comparison_csv_sha256": sha256(table)},
    }
    output = args.output_directory / "sentinel_exact_device_summary.json"
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
