#!/usr/bin/env python3
"""Load one frozen TFRecord batch through EfficientDet-Lite0 preprocessing."""

import argparse
import json


def describe_tensor(value):
    return {
        "shape": [int(dimension) for dimension in value.shape],
        "dtype": value.dtype.name,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record-pattern", required=True)
    parser.add_argument("--annotations-json", required=True)
    parser.add_argument("--size", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=8)
    arguments = parser.parse_args()

    import tensorflow as tf
    from tflite_model_maker import object_detector
    from effdet_background_compat import install_background_image_patch

    install_background_image_patch()

    data = object_detector.DataLoader(
        arguments.record_pattern,
        arguments.size,
        {1: "fire"},
        annotations_json_file=arguments.annotations_json,
    )
    specification = object_detector.EfficientDetLite0Spec(
        epochs=1,
        batch_size=arguments.batch_size,
        hparams={
            "mixed_precision": False,
            "skip_crowd_during_training": False,
        },
        tf_random_seed=20260729,
    )
    dataset = data.gen_dataset(
        specification, arguments.batch_size, is_training=True
    )
    images, labels = next(iter(dataset))
    positive_anchor_counts = [
        float(value)
        for value in tf.reshape(labels["mean_num_positives"], [-1]).numpy()
    ]
    evidence = {
        "schema_version": 1,
        "declared_size": len(data),
        "label_map": data.label_map,
        "model_name": specification.model_name,
        "input_image_size": specification.config.image_size,
        "image_batch": describe_tensor(images),
        "label_tensors": {
            key: describe_tensor(value)
            for key, value in labels.items()
            if hasattr(value, "shape") and hasattr(value, "dtype")
        },
        "images_finite": bool(tf.reduce_all(tf.math.is_finite(images))),
        "positive_anchor_counts": positive_anchor_counts,
        "zero_positive_samples_in_batch": sum(
            value == 0.0 for value in positive_anchor_counts
        ),
    }
    if evidence["declared_size"] != arguments.size:
        raise RuntimeError("DataLoader size mismatch")
    if not evidence["images_finite"]:
        raise RuntimeError("non-finite image tensor")
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
