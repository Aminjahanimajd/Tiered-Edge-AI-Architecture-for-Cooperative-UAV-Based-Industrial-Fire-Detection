#!/usr/bin/env python3
"""Record the exact tensor contract of a TensorFlow Lite artifact."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tensor_record(detail: dict) -> dict:
    scale, zero_point = detail["quantization"]
    return {
        "index": int(detail["index"]),
        "name": detail["name"],
        "shape": [int(value) for value in detail["shape"]],
        "shape_signature": [int(value) for value in detail["shape_signature"]],
        "dtype": str(detail["dtype"]),
        "quantization": {"scale": float(scale), "zero_point": int(zero_point)},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"refusing to overwrite {arguments.output}")

    import tensorflow as tf

    model = arguments.model.resolve()
    interpreter = tf.lite.Interpreter(model_path=str(model))
    interpreter.allocate_tensors()
    record = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model_path": str(model),
        "model_bytes": model.stat().st_size,
        "model_sha256": file_sha256(model),
        "tensorflow": tf.__version__,
        "inputs": [tensor_record(item) for item in interpreter.get_input_details()],
        "outputs": [tensor_record(item) for item in interpreter.get_output_details()],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(record, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
