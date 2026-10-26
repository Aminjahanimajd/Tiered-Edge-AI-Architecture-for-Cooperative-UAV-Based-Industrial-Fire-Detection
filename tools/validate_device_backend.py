#!/usr/bin/env python3
"""Run one synthetic-frame inference without starting ROS or a camera."""

from __future__ import print_function

import argparse
import json
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("backend", choices=("tensorrt", "tflite"))
    parser.add_argument("model_path")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--resize-mode", choices=("letterbox", "stretch"), default="letterbox")
    arguments = parser.parse_args()

    import numpy as np

    from drone_enhanced_core import decode_yolov8
    from drone_enhanced_nodes.backends import TensorRTBackend, TFLiteBackend
    from drone_enhanced_nodes.runtime_support import prepare_bgr_frame

    if arguments.backend == "tensorrt":
        backend = TensorRTBackend(arguments.model_path)
        class_names = ("fire", "smoke")
    else:
        backend = TFLiteBackend(arguments.model_path, arguments.threads)
        class_names = ("fire", "smoke", "non_fire")

    synthetic_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    tensor, transform = prepare_bgr_frame(
        synthetic_frame,
        backend.model_width,
        backend.model_height,
        arguments.resize_mode,
        backend.layout,
    )
    started_ns = int(time.monotonic() * 1000000000)
    output = backend.infer(tensor)
    finished_ns = int(time.monotonic() * 1000000000)
    detections = decode_yolov8(
        output,
        class_names,
        transform,
        confidence_threshold=0.15,
        iou_threshold=0.45,
        allowed_class_names=("fire",),
    )
    result = {
        "backend": arguments.backend,
        "input_shape": list(tensor.shape),
        "input_dtype": str(tensor.dtype),
        "output_shape": list(output.shape),
        "output_dtype": str(output.dtype),
        "synthetic_inference_ms": (finished_ns - started_ns) / 1000000.0,
        "decoded_fire_detections": len(detections),
        "status": "PASS",
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
