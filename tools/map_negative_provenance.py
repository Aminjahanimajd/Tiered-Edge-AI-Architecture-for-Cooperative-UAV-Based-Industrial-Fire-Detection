#!/usr/bin/env python3
"""Map Sentinel-only background images back to preserved source folders."""

from __future__ import print_function

import argparse
import collections
import hashlib
import json
import os
from pathlib import Path


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_names(path):
    return {
        item.name
        for item in path.iterdir()
        if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES
    }


def parse_source(value):
    if "=" not in value:
        raise argparse.ArgumentTypeError("source must use NAME=PATH")
    name, path = value.split("=", 1)
    if not name.strip():
        raise argparse.ArgumentTypeError("source name cannot be empty")
    source_path = Path(path).resolve()
    if not source_path.is_dir():
        raise argparse.ArgumentTypeError("source path does not exist: {}".format(path))
    return name.strip(), source_path


def analyze(base_root, sentinel_root, source_directories):
    base_root = Path(base_root).resolve()
    sentinel_root = Path(sentinel_root).resolve()
    source_index = collections.defaultdict(list)
    for source_name, directory in source_directories:
        for item in directory.iterdir():
            if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES:
                source_index[item.name].append((source_name, item))

    records = []
    counts = collections.Counter()
    for split in ("train", "valid", "test"):
        base_images = image_names(base_root / split / "images")
        sentinel_directory = sentinel_root / split / "images"
        added_names = sorted(image_names(sentinel_directory) - base_images)
        for filename in added_names:
            destination = sentinel_directory / filename
            candidates = source_index.get(filename, [])
            destination_hash = None
            matched = []
            if len(candidates) == 1:
                matched = [candidates[0][0]]
            elif len(candidates) > 1:
                destination_hash = sha256(destination)
                matched = [
                    name for name, path in candidates if sha256(path) == destination_hash
                ]
            if len(set(matched)) == 1:
                status = "matched"
                source_name = matched[0]
            elif not candidates:
                status = "unresolved_no_filename_match"
                source_name = None
            elif not matched:
                status = "unresolved_content_mismatch"
                source_name = None
            else:
                status = "ambiguous_identical_sources"
                source_name = None
            counts[(split, source_name or status)] += 1
            records.append(
                {
                    "split": split,
                    "filename": filename,
                    "source_dataset": source_name,
                    "status": status,
                    "candidate_sources": sorted(set(name for name, _ in candidates)),
                    "sha256": destination_hash,
                }
            )
    return {
        "schema_version": 1,
        "base_root": str(base_root),
        "sentinel_root": str(sentinel_root),
        "source_directories": [
            {"name": name, "path": str(path)} for name, path in source_directories
        ],
        "sentinel_only_image_count": len(records),
        "counts": [
            {"split": split, "source_or_status": source, "images": count}
            for (split, source), count in sorted(counts.items())
        ],
        "unresolved": [record for record in records if record["status"] != "matched"],
        "records": records,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--sentinel", required=True)
    parser.add_argument("--source", action="append", required=True, type=parse_source)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    report = analyze(arguments.base, arguments.sentinel, arguments.source)
    output_path = Path(arguments.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, sort_keys=True)
        output.write("\n")
    summary = {
        "sentinel_only_image_count": report["sentinel_only_image_count"],
        "counts": report["counts"],
        "unresolved_count": len(report["unresolved"]),
        "unresolved_examples": report["unresolved"][:20],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
