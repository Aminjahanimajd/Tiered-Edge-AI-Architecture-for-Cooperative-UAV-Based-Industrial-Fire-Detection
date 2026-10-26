#!/usr/bin/env python3
"""Deserialize a TensorRT engine and print binding metadata as JSON."""

from __future__ import print_function

import argparse
import hashlib
import json

import tensorrt as trt


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as engine_file:
        while True:
            chunk = engine_file.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("engine")
    args = parser.parse_args()

    logger = trt.Logger(trt.Logger.WARNING)
    with open(args.engine, "rb") as engine_file:
        serialized = engine_file.read()
    with trt.Runtime(logger) as runtime:
        engine = runtime.deserialize_cuda_engine(serialized)
    if engine is None:
        raise RuntimeError("TensorRT could not deserialize the engine")

    bindings = []
    for index in range(engine.num_bindings):
        bindings.append(
            {
                "index": index,
                "name": engine.get_binding_name(index),
                "is_input": bool(engine.binding_is_input(index)),
                "shape": [int(value) for value in engine.get_binding_shape(index)],
                "dtype": str(engine.get_binding_dtype(index)),
            }
        )

    payload = {
        "engine_path": args.engine,
        "sha256": sha256(args.engine),
        "tensorrt_version": trt.__version__,
        "num_bindings": int(engine.num_bindings),
        "has_implicit_batch_dimension": bool(engine.has_implicit_batch_dimension),
        "bindings": bindings,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
