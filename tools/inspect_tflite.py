#!/usr/bin/env python3
"""Print machine-readable metadata for a TFLite model without inference."""

from __future__ import print_function

import argparse
import hashlib
import json

from tflite_runtime.interpreter import Interpreter


def tensor_record(detail):
    quantization_parameters = detail.get("quantization_parameters", {})
    return {
        "name": detail.get("name"),
        "index": int(detail["index"]),
        "shape": [int(value) for value in detail["shape"]],
        "shape_signature": [
            int(value) for value in detail.get("shape_signature", [])
        ],
        "dtype": str(detail["dtype"]),
        "quantization": [
            float(detail.get("quantization", (0.0, 0))[0]),
            int(detail.get("quantization", (0.0, 0))[1]),
        ],
        "quantization_scales": [
            float(value)
            for value in quantization_parameters.get("scales", [])
        ],
        "quantization_zero_points": [
            int(value)
            for value in quantization_parameters.get("zero_points", [])
        ],
    }


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as model_file:
        while True:
            chunk = model_file.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("--threads", type=int, default=1)
    args = parser.parse_args()

    interpreter = Interpreter(model_path=args.model, num_threads=args.threads)
    payload = {
        "model_path": args.model,
        "sha256": sha256(args.model),
        "threads_requested": args.threads,
        "inputs": [tensor_record(item) for item in interpreter.get_input_details()],
        "outputs": [tensor_record(item) for item in interpreter.get_output_details()],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
