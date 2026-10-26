#!/usr/bin/env python3
"""Run one retained image and record raw TFLite outputs for semantic mapping."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

try:
    from predict_tflite_coco import dequantize, prepare_input
except ImportError:
    from tools.predict_tflite_coco import dequantize, prepare_input


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--integer-input-mode",
        choices=("raw_pixels", "quantize_scaled"),
        default="raw_pixels",
    )
    parser.add_argument("--float-input-scale", type=float, default=1.0)
    parser.add_argument("--float-input-offset", type=float, default=0.0)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"refusing to overwrite {arguments.output}")

    import numpy as np
    import tensorflow as tf
    from PIL import Image

    model = arguments.model.resolve()
    image = arguments.image.resolve()
    interpreter = tf.lite.Interpreter(model_path=str(model))
    interpreter.allocate_tensors()
    input_detail = interpreter.get_input_details()[0]
    _, height, width, _ = [int(value) for value in input_detail["shape"]]
    with Image.open(image) as source:
        rgb = np.asarray(source.convert("RGB").resize((width, height), Image.Resampling.BILINEAR))
    prepared = prepare_input(
        rgb, input_detail, arguments.float_input_scale, arguments.integer_input_mode,
        arguments.float_input_offset
    )
    interpreter.set_tensor(int(input_detail["index"]), prepared)
    interpreter.invoke()

    outputs = []
    for detail in interpreter.get_output_details():
        values = dequantize(interpreter.get_tensor(int(detail["index"])), detail).reshape(-1)
        outputs.append(
            {
                "index": int(detail["index"]),
                "name": detail["name"],
                "shape": [int(value) for value in detail["shape"]],
                "minimum": float(values.min()),
                "maximum": float(values.max()),
                "integer_like_fraction": float(np.mean(np.isclose(values, np.rint(values)))),
                "values": [float(value) for value in values.tolist()],
            }
        )
    record = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model_sha256": file_sha256(model),
        "image_sha256": file_sha256(image),
        "input_mode": arguments.integer_input_mode,
        "float_input_scale": arguments.float_input_scale,
        "float_input_offset": arguments.float_input_offset,
        "prepared_input_minimum": float(prepared.min()),
        "prepared_input_maximum": float(prepared.max()),
        "outputs": outputs,
        "interpretation_rule": (
            "Class tensors are integer-like; confidence tensors are continuous in [0,1]. "
            "Tensor roles are assigned only after inspecting these retained values and shapes."
        ),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(record, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
