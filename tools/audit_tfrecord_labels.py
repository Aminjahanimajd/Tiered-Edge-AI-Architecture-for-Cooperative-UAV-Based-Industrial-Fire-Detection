#!/usr/bin/env python3
"""Audit object-detection TFRecord label and box feature counts."""

import argparse
import collections
import glob
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record-pattern", required=True)
    arguments = parser.parse_args()

    import tensorflow as tf

    paths = sorted(glob.glob(arguments.record_pattern))
    if not paths:
        raise FileNotFoundError(arguments.record_pattern)

    label_counts = collections.Counter()
    records = 0
    positive_records = 0
    box_count_mismatches = 0
    examples = []
    for serialized in tf.data.TFRecordDataset(paths):
        example = tf.train.Example.FromString(bytes(serialized.numpy()))
        features = example.features.feature
        labels = list(features["image/object/class/label"].int64_list.value)
        coordinate_counts = [
            len(features[key].float_list.value)
            for key in (
                "image/object/bbox/xmin",
                "image/object/bbox/xmax",
                "image/object/bbox/ymin",
                "image/object/bbox/ymax",
            )
        ]
        records += 1
        label_counts.update(labels)
        positive_records += bool(labels)
        box_count_mismatches += len(set([len(labels)] + coordinate_counts)) != 1
        if labels and len(examples) < 5:
            examples.append(
                {
                    "source_id": features["image/source_id"].bytes_list.value[0].decode(),
                    "labels": labels,
                    "coordinate_counts": coordinate_counts,
                }
            )

    print(
        json.dumps(
            {
                "schema_version": 1,
                "record_pattern": arguments.record_pattern,
                "shard_count": len(paths),
                "records": records,
                "positive_records": positive_records,
                "background_records": records - positive_records,
                "label_counts": dict(sorted(label_counts.items())),
                "box_count_mismatches": box_count_mismatches,
                "positive_examples": examples,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
