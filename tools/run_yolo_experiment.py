#!/usr/bin/env python3
"""Run an evidence-capturing YOLO screening or sanity experiment."""

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import platform
import subprocess
import threading
import time
import traceback
from pathlib import Path


YOLO_MODELS = {
    "yolov8n_416": ("yolov8n.pt", 416),
    "yolov8n_640": ("yolov8n.pt", 640),
    "yolov8s_416": ("yolov8s.pt", 416),
    "yolov8s_640": ("yolov8s.pt", 640),
}
BLOCKING_PROCESSES = {"cs2.exe"}


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def parse_nvidia_query(text):
    fields = [field.strip() for field in text.strip().split(",")]
    if len(fields) != 5:
        raise ValueError("unexpected nvidia-smi query output")
    return {
        "temperature_c": float(fields[0]),
        "power_w": None if fields[1] in {"[N/A]", "N/A"} else float(fields[1]),
        "memory_used_mib": float(fields[2]),
        "memory_free_mib": float(fields[3]),
        "gpu_utilization_percent": float(fields[4]),
    }


def gpu_snapshot():
    command = [
        "nvidia-smi",
        "--query-gpu=temperature.gpu,power.draw,memory.used,memory.free,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    output = subprocess.check_output(command, text=True, stderr=subprocess.STDOUT)
    return parse_nvidia_query(output.splitlines()[0])


def blocking_processes(process_names):
    return sorted(name.lower() for name in process_names if name.lower() in BLOCKING_PROCESSES)


class ResourceMonitor:
    FIELDS = [
        "utc_time", "elapsed_s", "cpu_percent", "ram_used_mib",
        "temperature_c", "power_w", "memory_used_mib", "memory_free_mib",
        "gpu_utilization_percent", "sample_error"
    ]

    def __init__(self, output_csv, interval_seconds=2.0):
        self.output_csv = output_csv
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.thread = None
        self.start_monotonic = None

    def start(self):
        self.start_monotonic = time.monotonic()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=self.interval_seconds * 2 + 2)

    def _run(self):
        import psutil

        with self.output_csv.open("x", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=self.FIELDS)
            writer.writeheader()
            while not self.stop_event.is_set():
                row = {
                    "utc_time": utc_now(),
                    "elapsed_s": time.monotonic() - self.start_monotonic,
                    "cpu_percent": psutil.cpu_percent(interval=None),
                    "ram_used_mib": psutil.virtual_memory().used / (1024 * 1024),
                    "sample_error": "",
                }
                try:
                    row.update(gpu_snapshot())
                except Exception as error:
                    row["sample_error"] = repr(error)
                writer.writerow(row)
                output.flush()
                self.stop_event.wait(self.interval_seconds)


def artifact_hashes(run_directory):
    names = ["args.yaml", "results.csv", "weights/best.pt", "weights/last.pt"]
    results = {}
    for name in names:
        path = run_directory / name
        if path.is_file():
            results[name] = {"bytes": path.stat().st_size, "sha256": file_sha256(path)}
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model_id", choices=sorted(YOLO_MODELS))
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--dataset-yaml", required=True)
    parser.add_argument("--weights-directory", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--batch", type=float, default=-1)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--run-suffix", default="")
    parser.add_argument("--sanity", action="store_true")
    parser.add_argument("--ac-power-confirmed", action="store_true")
    arguments = parser.parse_args()

    import psutil
    import torch
    import ultralytics
    from ultralytics import YOLO

    matrix_path = Path(arguments.matrix).resolve()
    dataset_path = Path(arguments.dataset_yaml).resolve()
    weights_directory = Path(arguments.weights_directory).resolve()
    output_root = Path(arguments.output_root).resolve()
    with matrix_path.open("r", encoding="utf-8") as source:
        matrix = json.load(source)
    configured = {item["id"]: item for item in matrix["models"]}
    if arguments.model_id not in configured:
        raise ValueError("model is absent from comparison matrix")
    weights_name, input_size = YOLO_MODELS[arguments.model_id]
    if configured[arguments.model_id]["input_size"] != input_size:
        raise ValueError("matrix input size disagrees with runner")
    weights_path = weights_directory / weights_name
    if not weights_path.is_file():
        raise ValueError("pretrained weights are missing")
    if not dataset_path.is_file():
        raise ValueError("dataset YAML is missing")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    process_names = [process.info["name"] for process in psutil.process_iter(["name"])]
    blocked = blocking_processes(process_names)
    if blocked:
        raise RuntimeError("GPU-heavy blocking process is active: {}".format(blocked))
    initial_gpu = gpu_snapshot()
    if initial_gpu["temperature_c"] >= 70:
        raise RuntimeError("initial GPU temperature is at least 70 C")
    if initial_gpu["memory_free_mib"] < 3000:
        raise RuntimeError("less than 3000 MiB GPU memory is free")
    if not arguments.sanity and not arguments.ac_power_confirmed:
        raise RuntimeError("full training requires explicit AC-power confirmation")

    if arguments.batch > 0 and not arguments.batch.is_integer():
        raise ValueError("a positive batch size must be an integer")
    effective_batch = int(arguments.batch) if arguments.batch > 0 else arguments.batch
    run_name = arguments.model_id + ("_sanity" if arguments.sanity else "_screen_seed_{}".format(matrix["screening_seed"]))
    if arguments.run_suffix:
        run_name += "_" + arguments.run_suffix
    run_directory = output_root / run_name
    if run_directory.exists():
        raise ValueError("run directory already exists: {}".format(run_directory))
    evidence_directory = output_root / (run_name + "_evidence")
    evidence_directory.mkdir(parents=True, exist_ok=False)
    summary_path = evidence_directory / "run_summary.json"
    monitor = ResourceMonitor(evidence_directory / "resource_samples.csv")
    started_utc = utc_now()
    started_monotonic = time.monotonic()
    summary = {
        "schema_version": 1,
        "model_id": arguments.model_id,
        "mode": "sanity" if arguments.sanity else "screening",
        "started_utc": started_utc,
        "status": "running",
        "matrix_sha256": file_sha256(matrix_path),
        "dataset_yaml_sha256": file_sha256(dataset_path),
        "pretrained_weights_sha256": file_sha256(weights_path),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "ultralytics": ultralytics.__version__,
        "cuda_runtime": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0),
        "initial_gpu": initial_gpu,
        "parameters": {
            "input_size": input_size,
            "epochs": 1 if arguments.sanity else matrix["controlled_training_policy"]["maximum_epochs"],
            "fraction": 0.02 if arguments.sanity else 1.0,
            "batch": effective_batch,
            "workers": arguments.workers,
            "seed": matrix["screening_seed"],
        },
    }
    monitor.start()
    try:
        model = YOLO(str(weights_path))
        model.train(
            data=str(dataset_path),
            epochs=summary["parameters"]["epochs"],
            patience=matrix["controlled_training_policy"]["early_stopping_patience"],
            imgsz=input_size,
            batch=effective_batch,
            device=0,
            workers=arguments.workers,
            project=str(output_root),
            name=run_name,
            exist_ok=False,
            seed=matrix["screening_seed"],
            deterministic=True,
            amp=True,
            optimizer="AdamW",
            lr0=0.001,
            lrf=0.01,
            cos_lr=True,
            weight_decay=0.0005,
            warmup_epochs=3.0,
            hsv_h=0.01,
            hsv_s=0.40,
            hsv_v=0.25,
            degrees=0.0,
            translate=0.05,
            scale=0.20,
            shear=0.0,
            perspective=0.0,
            flipud=0.0,
            fliplr=0.5,
            mosaic=0.0,
            mixup=0.0,
            cutmix=0.0,
            copy_paste=0.0,
            close_mosaic=0,
            cache=False,
            plots=True,
            val=True,
            fraction=summary["parameters"]["fraction"],
            verbose=True,
        )
        summary["status"] = "completed"
    except Exception as error:
        summary["status"] = "failed"
        summary["error"] = repr(error)
        summary["traceback"] = traceback.format_exc()
        raise
    finally:
        monitor.stop()
        summary["ended_utc"] = utc_now()
        summary["elapsed_seconds"] = time.monotonic() - started_monotonic
        summary["artifact_hashes"] = artifact_hashes(run_directory)
        with summary_path.open("x", encoding="utf-8") as output:
            json.dump(summary, output, indent=2, sort_keys=True)
            output.write("\n")
        print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
