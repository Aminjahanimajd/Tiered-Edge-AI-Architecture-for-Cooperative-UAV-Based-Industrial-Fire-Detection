#!/usr/bin/env python3
"""Audit exact and near-image duplicates across a dataset manifest."""

from __future__ import print_function

import argparse
import collections
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageOps


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def difference_hash(image):
    grayscale = ImageOps.grayscale(image).resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(grayscale.getdata())
    value = 0
    for row in range(8):
        for column in range(8):
            value <<= 1
            if pixels[row * 9 + column] > pixels[row * 9 + column + 1]:
                value |= 1
    return value


def canonical_difference_hash(path):
    with Image.open(path) as image:
        image.load()
        direct = difference_hash(image)
        mirrored = difference_hash(ImageOps.mirror(image))
    return min(direct, mirrored)


def hamming_distance(first, second):
    return bin(int(first) ^ int(second)).count("1")


class BKNode(object):
    __slots__ = ("value", "record_indices", "children")

    def __init__(self, value, record_index):
        self.value = int(value)
        self.record_indices = [record_index]
        self.children = {}

    def insert(self, value, record_index):
        distance = hamming_distance(self.value, value)
        if distance == 0:
            self.record_indices.append(record_index)
            return
        child = self.children.get(distance)
        if child is None:
            self.children[distance] = BKNode(value, record_index)
        else:
            child.insert(value, record_index)

    def query(self, value, maximum_distance, output):
        distance = hamming_distance(self.value, value)
        if distance <= maximum_distance:
            output.append((distance, self.record_indices))
        minimum = distance - maximum_distance
        maximum = distance + maximum_distance
        for edge, child in self.children.items():
            if minimum <= edge <= maximum:
                child.query(value, maximum_distance, output)


def load_records(path):
    records = []
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            records.append(json.loads(line))
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("records_jsonl")
    parser.add_argument("--output", required=True)
    parser.add_argument("--maximum-dhash-distance", type=int, default=2)
    parser.add_argument("--maximum-examples", type=int, default=5000)
    arguments = parser.parse_args()
    records_path = Path(arguments.records_jsonl).resolve()
    output_path = Path(arguments.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = load_records(records_path)
    exact_index = collections.defaultdict(list)
    tree = None
    near_pair_count = 0
    near_cross_split_count = 0
    near_examples = []
    corrupt = []
    for index, record in enumerate(records):
        image_path = Path(record["image_path"])
        try:
            exact_hash = record.get("image_sha256") or file_sha256(image_path)
            perceptual_hash = canonical_difference_hash(image_path)
        except Exception as exc:
            corrupt.append(
                {"record_id": record["record_id"], "reason": str(exc)}
            )
            continue
        exact_index[exact_hash].append(index)
        matches = []
        if tree is not None:
            tree.query(perceptual_hash, arguments.maximum_dhash_distance, matches)
        for distance, matched_indices in matches:
            for matched_index in matched_indices:
                previous = records[matched_index]
                if previous["group_id"] == record["group_id"]:
                    continue
                near_pair_count += 1
                cross_split = previous["split"] != record["split"]
                near_cross_split_count += int(cross_split)
                if len(near_examples) < arguments.maximum_examples:
                    near_examples.append(
                        {
                            "distance": distance,
                            "cross_split": cross_split,
                            "first_record_id": previous["record_id"],
                            "first_group_id": previous["group_id"],
                            "first_split": previous["split"],
                            "second_record_id": record["record_id"],
                            "second_group_id": record["group_id"],
                            "second_split": record["split"],
                        }
                    )
        if tree is None:
            tree = BKNode(perceptual_hash, index)
        else:
            tree.insert(perceptual_hash, index)

    exact_duplicate_sets = []
    exact_cross_split_sets = 0
    for digest, indices in exact_index.items():
        if len(indices) <= 1:
            continue
        splits = sorted(set(records[index]["split"] for index in indices))
        groups = sorted(set(records[index]["group_id"] for index in indices))
        cross_split = len(splits) > 1
        exact_cross_split_sets += int(cross_split)
        exact_duplicate_sets.append(
            {
                "sha256": digest,
                "records": [records[index]["record_id"] for index in indices],
                "groups": groups,
                "splits": splits,
                "cross_split": cross_split,
            }
        )
    report = {
        "schema_version": 1,
        "records_jsonl": str(records_path),
        "record_count": len(records),
        "corrupt_or_unreadable": corrupt,
        "exact_duplicate_set_count": len(exact_duplicate_sets),
        "exact_cross_split_set_count": exact_cross_split_sets,
        "exact_duplicate_sets": exact_duplicate_sets,
        "perceptual_method": "mirror-invariant 64-bit difference hash",
        "maximum_dhash_distance": arguments.maximum_dhash_distance,
        "near_cross_group_pair_count": near_pair_count,
        "near_cross_split_pair_count": near_cross_split_count,
        "near_pair_examples_truncated": near_pair_count > len(near_examples),
        "near_pair_examples": near_examples,
        "interpretation": [
            "Difference-hash matches are screening candidates, not proof of duplicate content.",
            "Cross-split candidates require visual review or a stronger feature comparison.",
            "Known augmentation derivatives inside one group are intentionally not reported.",
        ],
    }
    with output_path.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, sort_keys=True)
        output.write("\n")
    print(
        json.dumps(
            {
                "record_count": len(records),
                "corrupt_or_unreadable": len(corrupt),
                "exact_duplicate_set_count": len(exact_duplicate_sets),
                "exact_cross_split_set_count": exact_cross_split_sets,
                "near_cross_group_pair_count": near_pair_count,
                "near_cross_split_pair_count": near_cross_split_count,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
