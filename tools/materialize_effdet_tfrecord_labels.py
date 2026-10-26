#!/usr/bin/env python3
"""Add numeric class labels to a derived copy of COCO TFRecord shards."""

import argparse
import glob
import hashlib
import json
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record-pattern", required=True)
    parser.add_argument("--output-directory", required=True)
    arguments = parser.parse_args()

    import tensorflow as tf

    sources = [Path(path).resolve() for path in sorted(glob.glob(arguments.record_pattern))]
    if not sources:
        raise FileNotFoundError(arguments.record_pattern)
    output_directory = Path(arguments.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=False)

    records = 0
    positive_records = 0
    labels_added = 0
    outputs = []
    for source in sources:
        destination = output_directory / source.name
        with tf.io.TFRecordWriter(str(destination)) as writer:
            for serialized in tf.data.TFRecordDataset([str(source)]):
                example = tf.train.Example.FromString(bytes(serialized.numpy()))
                features = example.features.feature
                labels = features["image/object/class/label"].int64_list.value
                texts = list(features["image/object/class/text"].bytes_list.value)
                coordinate_counts = [
                    len(features[key].float_list.value)
                    for key in (
                        "image/object/bbox/xmin",
                        "image/object/bbox/xmax",
                        "image/object/bbox/ymin",
                        "image/object/bbox/ymax",
                    )
                ]
                if not labels and texts:
                    unknown = sorted(set(texts) - {b"fire"})
                    if unknown:
                        raise ValueError("unknown class text: {!r}".format(unknown))
                    labels.extend([1] * len(texts))
                    labels_added += len(texts)
                if len(set([len(labels)] + coordinate_counts)) != 1:
                    raise ValueError(
                        "label/box count mismatch in {} record {}".format(
                            source.name, records
                        )
                    )
                records += 1
                positive_records += bool(labels)
                writer.write(example.SerializeToString())
        outputs.append(
            {
                "source_name": source.name,
                "source_sha256": sha256(source),
                "output_name": destination.name,
                "output_sha256": sha256(destination),
                "output_bytes": destination.stat().st_size,
            }
        )

    summary = {
        "schema_version": 1,
        "mapping": {"fire": 1},
        "records": records,
        "positive_records": positive_records,
        "background_records": records - positive_records,
        "labels_added": labels_added,
        "shards": outputs,
    }
    summary_path = output_directory / "materialization_summary.json"
    with summary_path.open("x", encoding="utf-8") as output:
        json.dump(summary, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
