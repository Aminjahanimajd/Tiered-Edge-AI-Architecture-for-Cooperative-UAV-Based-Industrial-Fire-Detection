#!/usr/bin/env python3
"""Run one hash-verified exact-device detector replay benchmark.

The tool is intentionally self-contained and compatible with older Python 3
installations used by the edge devices. Formal mode enforces the frozen 64
image, 20-warm-up, 200-measurement protocol. Outputs are non-overwriting and a
failed run still receives a summary and retained traceback.
"""

from __future__ import print_function

import argparse
import csv
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


FORMAL_IMAGE_COUNT = 64
FORMAL_WARMUP = 20
FORMAL_ITERATIONS = 200
FORMAL_RESOURCE_INTERVAL_SECONDS = 1.0


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def monotonic_ns():
    function = getattr(time, "monotonic_ns", None)
    return function() if function is not None else int(time.monotonic() * 1e9)


def file_sha256(path):
    digest = hashlib.sha256()
    with open(str(path), "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_key_values(path):
    result = {}
    try:
        with open(path, "r") as stream:
            for line in stream:
                key, separator, value = line.partition(":")
                if separator:
                    result[key.strip()] = value.strip()
    except (IOError, OSError):
        return {}
    return result


def read_cpu_ticks():
    try:
        with open("/proc/stat", "r") as stream:
            fields = stream.readline().split()
        values = [int(value) for value in fields[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values), idle
    except (IOError, OSError, ValueError, IndexError):
        return None


def resource_snapshot(previous_cpu=None):
    memory = read_key_values("/proc/meminfo")
    current_cpu = read_cpu_ticks()
    cpu_percent = None
    if previous_cpu is not None and current_cpu is not None:
        total_delta = current_cpu[0] - previous_cpu[0]
        idle_delta = current_cpu[1] - previous_cpu[1]
        if total_delta > 0:
            cpu_percent = 100.0 * (total_delta - idle_delta) / total_delta
    temperatures = []
    thermal_root = Path("/sys/class/thermal")
    if thermal_root.is_dir():
        for zone in sorted(thermal_root.glob("thermal_zone*")):
            try:
                sensor_type = (zone / "type").read_text().strip()
                raw = float((zone / "temp").read_text().strip())
            except (IOError, OSError, ValueError):
                continue
            temperatures.append(
                {
                    "zone": zone.name,
                    "type": sensor_type,
                    "raw": raw,
                    "celsius_if_millidegrees": raw / 1000.0,
                }
            )
    process = read_key_values("/proc/self/status")
    return {
        "utc": utc_now(),
        "monotonic_ns": monotonic_ns(),
        "cpu_total_percent": cpu_percent,
        "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
        "mem_total": memory.get("MemTotal"),
        "mem_available": memory.get("MemAvailable"),
        "swap_total": memory.get("SwapTotal"),
        "swap_free": memory.get("SwapFree"),
        "process_vm_rss": process.get("VmRSS"),
        "process_vm_hwm": process.get("VmHWM"),
        "thermal_zones": temperatures,
        "_cpu_ticks": current_cpu,
    }


class ResourceSampler(object):
    def __init__(self, interval_seconds):
        self.interval_seconds = float(interval_seconds)
        self.samples = []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="resource-sampler")
        self.thread.daemon = True

    def _run(self):
        previous = None
        while not self.stop_event.is_set():
            sample = resource_snapshot(previous)
            previous = sample.pop("_cpu_ticks")
            self.samples.append(sample)
            self.stop_event.wait(self.interval_seconds)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=max(5.0, self.interval_seconds * 2.0))


def verify_calibration(manifest_path, image_root):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    rows = sorted(manifest["records"], key=lambda row: int(row["image_id"]))
    verified = []
    for row in rows:
        path = Path(image_root) / row["file_name"]
        if not path.is_file():
            raise FileNotFoundError(str(path))
        observed = file_sha256(path)
        if observed != row["sha256"]:
            raise RuntimeError("calibration image hash mismatch: {}".format(path))
        verified.append((row, path))
    return manifest, verified


def prepare_yolo(frame, backend):
    from drone_enhanced_nodes.runtime_support import prepare_bgr_frame

    return prepare_bgr_frame(
        frame,
        backend.model_width,
        backend.model_height,
        "letterbox",
        backend.layout,
    )


class OnnxYoloBackend(object):
    def __init__(self, model_path, provider):
        import onnxruntime as ort

        providers = [provider] if provider else None
        self.session = ort.InferenceSession(str(model_path), providers=providers)
        inputs = self.session.get_inputs()
        outputs = self.session.get_outputs()
        if len(inputs) != 1 or len(outputs) != 1:
            raise ValueError("ONNX YOLO requires exactly one input and one output")
        shape = inputs[0].shape
        if len(shape) != 4 or shape[0] != 1 or shape[1] != 3:
            raise ValueError("expected static NCHW ONNX input, received {}".format(shape))
        if not all(isinstance(value, int) and value > 0 for value in shape):
            raise ValueError("dynamic ONNX input is not accepted in formal screening")
        self.input_name = inputs[0].name
        self.output_name = outputs[0].name
        self.layout = "NCHW"
        self.model_height = int(shape[2])
        self.model_width = int(shape[3])
        self.runtime = "onnxruntime"
        self.runtime_version = ort.__version__
        self.providers = self.session.get_providers()

    def infer(self, tensor):
        return self.session.run([self.output_name], {self.input_name: tensor})[0]


class DetectionPostprocessTFLiteBackend(object):
    def __init__(self, model_path, threads, boxes, classes, scores, count):
        try:
            import tflite_runtime.interpreter as tflite

            runtime_name = "tflite_runtime"
            runtime_version = getattr(tflite, "__version__", None)
        except ImportError:
            import tensorflow as tensorflow

            tflite = tensorflow.lite
            runtime_name = "tensorflow.lite"
            runtime_version = tensorflow.__version__
        self.interpreter = tflite.Interpreter(
            model_path=str(model_path), num_threads=int(threads)
        )
        self.interpreter.allocate_tensors()
        inputs = self.interpreter.get_input_details()
        if len(inputs) != 1:
            raise ValueError("TFLite detector requires exactly one input")
        self.input = inputs[0]
        shape = [int(value) for value in self.input["shape"]]
        if len(shape) != 4 or shape[0] != 1 or shape[3] != 3:
            raise ValueError("expected static NHWC TFLite input, received {}".format(shape))
        output_by_index = {
            int(item["index"]): item for item in self.interpreter.get_output_details()
        }
        requested = {
            "boxes": int(boxes),
            "classes": int(classes),
            "scores": int(scores),
            "count": int(count),
        }
        unknown = {name: value for name, value in requested.items() if value not in output_by_index}
        if unknown:
            raise ValueError("missing TFLite output tensor indices: {}".format(unknown))
        self.outputs = requested
        self.output_details = output_by_index
        self.model_height = shape[1]
        self.model_width = shape[2]
        self.layout = "NHWC"
        self.runtime = runtime_name
        self.runtime_version = runtime_version
        self.providers = []

    def prepare(self, frame, float_scale, float_offset):
        import cv2
        import numpy as np

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(
            rgb, (self.model_width, self.model_height), interpolation=cv2.INTER_LINEAR
        )
        dtype = self.input["dtype"]
        if np.issubdtype(dtype, np.floating):
            tensor = resized.astype(dtype) * float(float_scale) + float(float_offset)
        else:
            tensor = resized.astype(dtype)
        return tensor[None, ...], {
            "original_width": int(frame.shape[1]),
            "original_height": int(frame.shape[0]),
        }

    def infer(self, tensor):
        self.interpreter.set_tensor(int(self.input["index"]), tensor)
        self.interpreter.invoke()
        return {
            name: self.interpreter.get_tensor(index)
            for name, index in self.outputs.items()
        }

    def decode_count(self, output, score_floor, class_id_offset):
        import numpy as np

        count = min(
            int(round(float(np.asarray(output["count"]).reshape(-1)[0]))),
            int(np.asarray(output["scores"]).reshape(-1).shape[0]),
        )
        scores = np.asarray(output["scores"]).reshape(-1)[:count]
        classes = np.asarray(output["classes"]).reshape(-1)[:count]
        accepted = 0
        for class_value, score in zip(classes, scores):
            category_id = int(round(float(class_value))) + int(class_id_offset)
            if category_id == 1 and float(score) >= float(score_floor):
                accepted += 1
        return accepted


def start_tegrastats(path, interval_seconds, output_path):
    if not path:
        return None, None
    executable = Path(path)
    if not executable.is_file():
        raise FileNotFoundError("tegrastats executable not found: {}".format(path))
    stream = open(str(output_path), "w")
    process = subprocess.Popen(
        [str(executable), "--interval", str(int(interval_seconds * 1000))],
        stdout=stream,
        stderr=subprocess.STDOUT,
    )
    return process, stream


def stop_process(process, stream):
    if process is not None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if stream is not None:
        stream.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument(
        "--backend",
        choices=("tensorrt_yolo", "onnx_yolo", "tflite_detection_postprocess"),
        required=True,
    )
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--expected-model-sha256", required=True)
    parser.add_argument("--calibration-manifest", type=Path, required=True)
    parser.add_argument("--expected-calibration-manifest-sha256", required=True)
    parser.add_argument("--image-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--formal", action="store_true")
    parser.add_argument("--warmup", type=int, default=FORMAL_WARMUP)
    parser.add_argument("--iterations", type=int, default=FORMAL_ITERATIONS)
    parser.add_argument(
        "--resource-interval", type=float, default=FORMAL_RESOURCE_INTERVAL_SECONDS
    )
    parser.add_argument("--onnx-provider", default="CPUExecutionProvider")
    parser.add_argument(
        "--yolo-class-names",
        nargs="+",
        default=["fire"],
        help="ordered YOLO output classes; frozen fire-only screening uses one class",
    )
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--boxes-tensor-index", type=int)
    parser.add_argument("--classes-tensor-index", type=int)
    parser.add_argument("--scores-tensor-index", type=int)
    parser.add_argument("--count-tensor-index", type=int)
    parser.add_argument("--class-id-offset", type=int, default=1)
    parser.add_argument("--score-floor", type=float, default=0.15)
    parser.add_argument("--float-input-scale", type=float, default=1.0)
    parser.add_argument("--float-input-offset", type=float, default=0.0)
    parser.add_argument("--delegate-label", default="none_declared")
    parser.add_argument("--tegrastats")
    arguments = parser.parse_args()

    if arguments.output_directory.exists():
        parser.error("output directory exists; evidence is non-overwriting")
    if arguments.warmup < 0 or arguments.iterations <= 0 or arguments.resource_interval <= 0:
        parser.error("warmup, iterations, and resource interval are invalid")
    if arguments.formal and (
        arguments.warmup != FORMAL_WARMUP
        or arguments.iterations != FORMAL_ITERATIONS
        or arguments.resource_interval != FORMAL_RESOURCE_INTERVAL_SECONDS
    ):
        parser.error("formal mode requires exactly 20 warm-ups, 200 iterations, and 1 Hz resources")
    tflite_indices = (
        arguments.boxes_tensor_index,
        arguments.classes_tensor_index,
        arguments.scores_tensor_index,
        arguments.count_tensor_index,
    )
    if arguments.backend == "tflite_detection_postprocess" and any(
        value is None for value in tflite_indices
    ):
        parser.error("TFLite detection-postprocess tensor indices are required")
    if arguments.backend in ("tensorrt_yolo", "onnx_yolo") and (
        not arguments.yolo_class_names or "fire" not in arguments.yolo_class_names
    ):
        parser.error("YOLO class names must contain fire")

    output = arguments.output_directory
    output.mkdir(parents=True)
    summary_path = output / "run_summary.json"
    latency_path = output / "latency_samples.csv"
    resource_path = output / "resource_samples.jsonl"
    tegrastats_path = output / "tegrastats.log"
    summary = {
        "schema_version": 1,
        "status": "RUNNING",
        "started_utc": utc_now(),
        "started_monotonic_ns": monotonic_ns(),
        "safety_state": "camera-free replay; no ROS command, flight-controller, arm, or motor interface",
        "formal_mode": bool(arguments.formal),
        "model_id": arguments.model_id,
        "backend": arguments.backend,
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "parameters": {
            "warmup_inferences": arguments.warmup,
            "measured_inferences": arguments.iterations,
            "resource_interval_seconds": arguments.resource_interval,
            "score_floor": arguments.score_floor,
            "delegate_label_operator_declared": arguments.delegate_label,
            "yolo_class_names": list(arguments.yolo_class_names),
        },
        "claim_boundary": (
            "Exact-device camera-free replay feasibility and resource evidence only; "
            "not accuracy, live-camera, endurance, flight, or industrial reliability."
        ),
    }
    sampler = None
    tegrastats_process = None
    tegrastats_stream = None
    exit_code = 1
    try:
        model_hash = file_sha256(arguments.model)
        if model_hash != arguments.expected_model_sha256:
            raise RuntimeError("model SHA-256 differs from the frozen matrix")
        calibration_hash = file_sha256(arguments.calibration_manifest)
        if calibration_hash != arguments.expected_calibration_manifest_sha256:
            raise RuntimeError("calibration manifest SHA-256 differs from the frozen matrix")
        calibration, verified = verify_calibration(
            arguments.calibration_manifest, arguments.image_root
        )
        if arguments.formal and len(verified) != FORMAL_IMAGE_COUNT:
            raise RuntimeError("formal mode requires exactly 64 verified replay images")
        summary["model"] = {
            "path": str(arguments.model),
            "bytes": arguments.model.stat().st_size,
            "sha256": model_hash,
        }
        summary["calibration"] = {
            "manifest": str(arguments.calibration_manifest),
            "manifest_sha256": calibration_hash,
            "verified_image_count": len(verified),
            "selection_method": calibration.get("selection_method"),
        }

        if arguments.backend == "tensorrt_yolo":
            from drone_enhanced_nodes.backends import TensorRTBackend

            backend = TensorRTBackend(str(arguments.model))
            runtime = "TensorRT"
            runtime_version = getattr(backend._trt, "__version__", None)
            providers = ["CUDA/TensorRT"]
        elif arguments.backend == "onnx_yolo":
            backend = OnnxYoloBackend(arguments.model, arguments.onnx_provider)
            runtime = backend.runtime
            runtime_version = backend.runtime_version
            providers = backend.providers
        else:
            backend = DetectionPostprocessTFLiteBackend(
                arguments.model,
                arguments.threads,
                arguments.boxes_tensor_index,
                arguments.classes_tensor_index,
                arguments.scores_tensor_index,
                arguments.count_tensor_index,
            )
            runtime = backend.runtime
            runtime_version = backend.runtime_version
            providers = backend.providers
        summary["runtime"] = {
            "name": runtime,
            "version": runtime_version,
            "providers": providers,
        }
        summary["model_input"] = {
            "layout": backend.layout,
            "height": backend.model_height,
            "width": backend.model_width,
        }

        sampler = ResourceSampler(arguments.resource_interval)
        sampler.start()
        tegrastats_process, tegrastats_stream = start_tegrastats(
            arguments.tegrastats, arguments.resource_interval, tegrastats_path
        )

        import cv2
        from drone_enhanced_core import decode_yolov8

        def execute(row_path):
            row, image_path = row_path
            started = monotonic_ns()
            frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if frame is None:
                raise RuntimeError("OpenCV could not decode {}".format(image_path))
            loaded = monotonic_ns()
            if arguments.backend == "tflite_detection_postprocess":
                tensor, transform = backend.prepare(
                    frame, arguments.float_input_scale, arguments.float_input_offset
                )
            else:
                tensor, transform = prepare_yolo(frame, backend)
            prepared = monotonic_ns()
            raw = backend.infer(tensor)
            inferred = monotonic_ns()
            if arguments.backend == "tflite_detection_postprocess":
                detection_count = backend.decode_count(
                    raw, arguments.score_floor, arguments.class_id_offset
                )
            else:
                detections = decode_yolov8(
                    raw,
                    tuple(arguments.yolo_class_names),
                    transform,
                    confidence_threshold=arguments.score_floor,
                    iou_threshold=0.45,
                    allowed_class_names=("fire",),
                )
                detection_count = len(detections)
            decoded = monotonic_ns()
            return {
                "image_id": int(row["image_id"]),
                "file_name": row["file_name"],
                "image_sha256": row["sha256"],
                "load_decode_ms": (loaded - started) / 1e6,
                "preprocess_ms": (prepared - loaded) / 1e6,
                "inference_ms": (inferred - prepared) / 1e6,
                "postprocess_ms": (decoded - inferred) / 1e6,
                "pipeline_ms": (decoded - started) / 1e6,
                "decoded_fire_detection_count": detection_count,
            }

        for index in range(arguments.warmup):
            execute(verified[index % len(verified)])
        samples = []
        for index in range(arguments.iterations):
            sample = execute(verified[index % len(verified)])
            sample["iteration_index"] = index
            samples.append(sample)

        with latency_path.open("x", newline="", encoding="utf-8") as stream:
            fieldnames = [
                "iteration_index", "image_id", "file_name", "image_sha256",
                "load_decode_ms", "preprocess_ms", "inference_ms",
                "postprocess_ms", "pipeline_ms", "decoded_fire_detection_count",
            ]
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(samples)
        summary["status"] = "PASS"
        summary["latency_sample_count"] = len(samples)
        summary["latency_samples_sha256"] = file_sha256(latency_path)
        exit_code = 0
    except Exception as error:
        summary["status"] = "FAIL"
        summary["error"] = repr(error)
        summary["traceback"] = traceback.format_exc()
    finally:
        if sampler is not None:
            sampler.stop()
        stop_process(tegrastats_process, tegrastats_stream)
        if sampler is not None:
            with resource_path.open("x", encoding="utf-8", newline="\n") as stream:
                for sample in sampler.samples:
                    stream.write(json.dumps(sample, sort_keys=True) + "\n")
            summary["resource_sample_count"] = len(sampler.samples)
            summary["resource_samples_sha256"] = file_sha256(resource_path)
        if tegrastats_path.is_file():
            summary["tegrastats_sha256"] = file_sha256(tegrastats_path)
        summary["finished_utc"] = utc_now()
        summary["finished_monotonic_ns"] = monotonic_ns()
        with summary_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(summary, stream, indent=2, sort_keys=True)
            stream.write("\n")
    print(
        json.dumps(
            {
                "status": summary["status"],
                "output": str(output),
                "summary_sha256": file_sha256(summary_path),
                "error": summary.get("error"),
            },
            sort_keys=True,
        )
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
