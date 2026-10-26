#!/usr/bin/env python3
"""Benchmark one deployed backend without ROS, a camera, or flight control.

The program emits one JSON object containing every warm-up and measured timing.
It intentionally uses a fixed synthetic frame, so its results characterize
runtime execution only and never model accuracy.
"""

from __future__ import print_function

import argparse
import hashlib
import json
import math
import os
import platform
import socket
import statistics
import time
from datetime import datetime, timezone


def monotonic_ns():
    function = getattr(time, "monotonic_ns", None)
    if function is not None:
        return function()
    return int(time.monotonic() * 1000000000)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values, percentage):
    """Return a linearly interpolated percentile for a non-empty sequence."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    percentage = float(percentage)
    if not 0.0 <= percentage <= 100.0:
        raise ValueError("percentage must be in [0, 100]")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentage / 100.0
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize(values):
    values = [float(value) for value in values]
    if not values:
        raise ValueError("summary requires at least one value")
    minimum = min(values)
    maximum = max(values)
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "minimum": minimum,
        "maximum": maximum,
        "range": maximum - minimum,
        "population_variance": statistics.pvariance(values),
        "population_standard_deviation": statistics.pstdev(values),
        "p05": percentile(values, 5),
        "p25": percentile(values, 25),
        "p75": percentile(values, 75),
        "p95": percentile(values, 95),
    }


def _read_key_value_file(path):
    values = {}
    try:
        with open(path, "r") as source:
            for line in source:
                key, separator, value = line.partition(":")
                if separator:
                    values[key.strip()] = value.strip()
    except (IOError, OSError):
        return None
    return values


def resource_snapshot():
    snapshot = {"utc": utc_now(), "monotonic_ns": monotonic_ns()}
    try:
        snapshot["load_average_1m_5m_15m"] = list(os.getloadavg())
    except (AttributeError, OSError):
        snapshot["load_average_1m_5m_15m"] = None
    memory = _read_key_value_file("/proc/meminfo")
    if memory is not None:
        snapshot["proc_meminfo"] = {
            key: memory.get(key)
            for key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")
        }
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        snapshot["process_max_rss_kib"] = usage.ru_maxrss
        snapshot["process_user_cpu_seconds"] = usage.ru_utime
        snapshot["process_system_cpu_seconds"] = usage.ru_stime
    except (ImportError, AttributeError):
        pass
    thermal = []
    thermal_root = "/sys/class/thermal"
    try:
        names = sorted(os.listdir(thermal_root))
    except (IOError, OSError):
        names = []
    for name in names:
        if not name.startswith("thermal_zone"):
            continue
        base = os.path.join(thermal_root, name)
        try:
            with open(os.path.join(base, "type"), "r") as source:
                sensor_type = source.read().strip()
            with open(os.path.join(base, "temp"), "r") as source:
                raw_temperature = float(source.read().strip())
        except (IOError, OSError, ValueError):
            continue
        thermal.append(
            {
                "zone": name,
                "type": sensor_type,
                "raw_temperature": raw_temperature,
                "assumed_celsius_if_millidegrees": raw_temperature / 1000.0,
            }
        )
    snapshot["thermal_zones"] = thermal
    return snapshot


def execute_pipeline(backend, frame, resize_mode, class_names):
    from drone_enhanced_core import decode_yolov8
    from drone_enhanced_nodes.runtime_support import prepare_bgr_frame

    started_ns = monotonic_ns()
    tensor, transform = prepare_bgr_frame(
        frame,
        backend.model_width,
        backend.model_height,
        resize_mode,
        backend.layout,
    )
    prepared_ns = monotonic_ns()
    output = backend.infer(tensor)
    inferred_ns = monotonic_ns()
    detections = decode_yolov8(
        output,
        class_names,
        transform,
        confidence_threshold=0.15,
        iou_threshold=0.45,
        allowed_class_names=("fire",),
    )
    decoded_ns = monotonic_ns()
    return {
        "preprocess_ms": (prepared_ns - started_ns) / 1000000.0,
        "inference_ms": (inferred_ns - prepared_ns) / 1000000.0,
        "decode_ms": (decoded_ns - inferred_ns) / 1000000.0,
        "pipeline_ms": (decoded_ns - started_ns) / 1000000.0,
        "decoded_fire_detections": len(detections),
        "input_shape": list(tensor.shape),
        "input_dtype": str(tensor.dtype),
        "output_shape": list(output.shape),
        "output_dtype": str(output.dtype),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", choices=("tensorrt", "tflite"))
    parser.add_argument("model_path")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--resize-mode", choices=("letterbox", "stretch"), default="letterbox")
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=50)
    arguments = parser.parse_args()
    if arguments.warmup < 0:
        parser.error("--warmup must be non-negative")
    if arguments.iterations <= 0:
        parser.error("--iterations must be positive")
    if arguments.threads <= 0:
        parser.error("--threads must be positive")

    import numpy as np

    from drone_enhanced_nodes.backends import TensorRTBackend, TFLiteBackend

    model_path = os.path.abspath(arguments.model_path)
    result = {
        "schema_version": 1,
        "benchmark_scope": "camera_free_fixed_black_synthetic_frame",
        "accuracy_claim_permitted": False,
        "started_utc": utc_now(),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "backend": arguments.backend,
        "model_path": model_path,
        "model_sha256": file_sha256(model_path),
        "resize_mode": arguments.resize_mode,
        "tflite_threads": arguments.threads if arguments.backend == "tflite" else None,
        "warmup_count": arguments.warmup,
        "iteration_count": arguments.iterations,
        "synthetic_frame": {
            "shape": [480, 640, 3],
            "dtype": "uint8",
            "bgr_fill_value": [0, 0, 0],
        },
        "resource_before_backend_load": resource_snapshot(),
    }
    load_started_ns = monotonic_ns()
    if arguments.backend == "tensorrt":
        backend = TensorRTBackend(model_path)
        class_names = ("fire", "smoke")
        result["binding_metadata"] = backend.binding_metadata
    else:
        backend = TFLiteBackend(model_path, arguments.threads)
        class_names = ("fire", "smoke", "non_fire")
        result["tflite_input_shape"] = [
            int(value) for value in backend.input_metadata["shape"]
        ]
        result["tflite_input_dtype"] = str(backend.input_metadata["dtype"])
        result["tflite_output_shape"] = [
            int(value) for value in backend.output_metadata["shape"]
        ]
        result["tflite_output_dtype"] = str(backend.output_metadata["dtype"])
    result["backend_load_ms"] = (monotonic_ns() - load_started_ns) / 1000000.0
    result["resource_after_backend_load"] = resource_snapshot()

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    warmup_samples = []
    for index in range(arguments.warmup):
        sample = execute_pipeline(backend, frame, arguments.resize_mode, class_names)
        sample["warmup_index"] = index
        warmup_samples.append(sample)

    samples = []
    for index in range(arguments.iterations):
        sample = execute_pipeline(backend, frame, arguments.resize_mode, class_names)
        sample["iteration_index"] = index
        samples.append(sample)

    result["warmup_samples"] = warmup_samples
    result["samples"] = samples
    result["summaries_ms"] = {
        key: summarize([sample[key] for sample in samples])
        for key in ("preprocess_ms", "inference_ms", "decode_ms", "pipeline_ms")
    }
    result["decoded_fire_detection_counts"] = [
        sample["decoded_fire_detections"] for sample in samples
    ]
    result["resource_after_benchmark"] = resource_snapshot()
    result["finished_utc"] = utc_now()
    result["status"] = "PASS"
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
