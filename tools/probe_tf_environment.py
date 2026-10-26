#!/usr/bin/env python3
"""Probe the isolated TensorFlow detector environment and execute a GPU op."""

import json
import importlib.metadata
import platform


def main():
    import tensorflow as tf
    import tensorflow_datasets as tfds
    from mediapipe_model_maker import object_detector

    devices = tf.config.list_physical_devices("GPU")
    matrix = tf.random.uniform((256, 256), seed=20260729)
    product = tf.linalg.matmul(matrix, matrix)
    evidence = {
        "schema_version": 1,
        "python": platform.python_version(),
        "tensorflow": tf.__version__,
        "tensorflow_datasets": tfds.__version__,
        "tensorflow_metadata": importlib.metadata.version("tensorflow-metadata"),
        "mediapipe": importlib.metadata.version("mediapipe"),
        "mediapipe_model_maker": importlib.metadata.version("mediapipe-model-maker"),
        "gpu_devices": [device.name for device in devices],
        "kernel_device": product.device,
        "kernel_sum": float(tf.reduce_sum(product)),
        "mediapipe_object_detector_import": object_detector.__name__,
    }
    if not devices or "GPU" not in product.device.upper():
        raise RuntimeError("TensorFlow GPU kernel gate failed: {}".format(evidence))
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
