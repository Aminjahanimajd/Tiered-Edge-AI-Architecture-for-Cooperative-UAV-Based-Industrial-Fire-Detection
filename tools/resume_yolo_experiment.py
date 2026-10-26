#!/usr/bin/env python3
"""Resume an interrupted Ultralytics run with separate recovery evidence."""

import argparse
import json
import platform
import time
import traceback
from pathlib import Path

from run_yolo_experiment import (
    ResourceMonitor,
    artifact_hashes,
    file_sha256,
    gpu_snapshot,
    utc_now,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--evidence-directory", required=True)
    parser.add_argument("--ac-power-confirmed", action="store_true")
    arguments = parser.parse_args()

    import torch
    import ultralytics
    from ultralytics import YOLO

    run_directory = Path(arguments.run_directory).resolve()
    evidence_directory = Path(arguments.evidence_directory).resolve()
    last_checkpoint = run_directory / "weights" / "last.pt"
    results_csv = run_directory / "results.csv"
    if not arguments.ac_power_confirmed:
        raise RuntimeError("resume requires explicit AC-power confirmation")
    if not last_checkpoint.is_file() or not results_csv.is_file():
        raise ValueError("resume checkpoint or results.csv is missing")
    if evidence_directory.exists():
        raise ValueError("recovery evidence directory already exists")
    initial_gpu = gpu_snapshot()
    if initial_gpu["temperature_c"] >= 70:
        raise RuntimeError("initial GPU temperature is at least 70 C")
    if initial_gpu["memory_free_mib"] < 3000:
        raise RuntimeError("less than 3000 MiB GPU memory is free")

    completed_epochs_before_resume = sum(1 for _ in results_csv.open("r", encoding="utf-8")) - 1
    evidence_directory.mkdir(parents=True, exist_ok=False)
    monitor = ResourceMonitor(evidence_directory / "resource_samples.csv")
    summary_path = evidence_directory / "run_summary.json"
    summary = {
        "schema_version": 1,
        "model_id": "yolov8n_640",
        "mode": "screening_resume",
        "status": "running",
        "started_utc": utc_now(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "ultralytics": ultralytics.__version__,
        "cuda_runtime": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0),
        "initial_gpu": initial_gpu,
        "completed_epochs_before_resume": completed_epochs_before_resume,
        "checkpoint_before_resume": {
            "bytes": last_checkpoint.stat().st_size,
            "sha256": file_sha256(last_checkpoint),
        },
    }
    started = time.monotonic()
    monitor.start()
    try:
        model = YOLO(str(last_checkpoint))
        model.train(resume=True)
        summary["status"] = "completed"
    except Exception as error:
        summary["status"] = "failed"
        summary["error"] = repr(error)
        summary["traceback"] = traceback.format_exc()
        raise
    finally:
        monitor.stop()
        summary["ended_utc"] = utc_now()
        summary["elapsed_seconds"] = time.monotonic() - started
        summary["completed_epochs_after_resume"] = (
            sum(1 for _ in results_csv.open("r", encoding="utf-8")) - 1
        )
        summary["artifact_hashes"] = artifact_hashes(run_directory)
        with summary_path.open("x", encoding="utf-8") as output:
            json.dump(summary, output, indent=2, sort_keys=True)
            output.write("\n")
        print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
