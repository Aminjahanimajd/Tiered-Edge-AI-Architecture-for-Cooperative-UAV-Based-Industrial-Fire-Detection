#!/usr/bin/env python3
"""Probe the isolated TFLite Model Maker EfficientDet-Lite0 environment."""

import importlib.metadata
import json
import platform


def main():
    import tensorflow as tf
    from tflite_model_maker import model_spec, object_detector

    specification = model_spec.get("efficientdet_lite0")
    devices = tf.config.list_physical_devices("GPU")
    kernel_device = None
    kernel_sum = None
    if devices:
        matrix = tf.random.uniform((256, 256), seed=20260729)
        product = tf.linalg.matmul(matrix, matrix)
        kernel_device = product.device
        kernel_sum = float(tf.reduce_sum(product))
    evidence = {
        "schema_version": 1,
        "python": platform.python_version(),
        "tensorflow": tf.__version__,
        "tflite_model_maker": importlib.metadata.version("tflite-model-maker"),
        "model_spec_name": specification.model_name,
        "input_image_size": specification.config.image_size,
        "object_detector_import": object_detector.__name__,
        "gpu_devices": [device.name for device in devices],
        "kernel_device": kernel_device,
        "kernel_sum": kernel_sum,
    }
    print(json.dumps(evidence, indent=2, sort_keys=True))
    if not devices or not kernel_device or "GPU" not in kernel_device.upper():
        raise RuntimeError("EfficientDet TensorFlow GPU kernel gate failed")


if __name__ == "__main__":
    main()
