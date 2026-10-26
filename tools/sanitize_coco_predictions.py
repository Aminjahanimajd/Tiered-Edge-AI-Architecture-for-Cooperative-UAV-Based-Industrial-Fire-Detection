#!/usr/bin/env python3
"""Create an evaluable COCO prediction file while preserving raw predictions."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sanitize(predictions: list[dict]) -> tuple[list[dict], list[dict]]:
    retained, excluded = [], []
    for index, prediction in enumerate(predictions):
        try:
            values = [float(value) for value in prediction["bbox"]]
            valid = len(values) == 4 and all(math.isfinite(value) for value in values)
            valid = valid and values[2] > 0.0 and values[3] > 0.0
        except (KeyError, TypeError, ValueError):
            valid = False
        if valid:
            retained.append(prediction)
        else:
            excluded.append({"index": index, "reason": "nonfinite_or_nonpositive_bbox"})
    return retained, excluded


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists() or arguments.summary.exists():
        raise FileExistsError("refusing to overwrite sanitized evidence")
    raw = json.loads(arguments.input.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise TypeError("COCO predictions must be a JSON list")
    retained, excluded = sanitize(raw)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(retained, stream, separators=(",", ":"))
        stream.write("\n")
    summary = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "rule": "exclude only predictions with a non-finite or nonpositive-width/height COCO bbox",
        "input_count": len(raw),
        "retained_count": len(retained),
        "excluded_count": len(excluded),
        "excluded": excluded,
        "input_sha256": file_sha256(arguments.input),
        "output_sha256": file_sha256(arguments.output),
        "tool_sha256": file_sha256(Path(__file__)),
    }
    with arguments.summary.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
