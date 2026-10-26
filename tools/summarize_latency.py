#!/usr/bin/env python3
"""Summarize retained per-image latency without modifying raw observations."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import statistics
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latency-csv", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--column", default="inference_ms")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise FileExistsError(f"refusing to overwrite {arguments.output}")
    with arguments.latency_csv.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or arguments.column not in rows[0]:
        raise ValueError(f"missing observations or column {arguments.column}")
    values = [float(row[arguments.column]) for row in rows]
    if not all(math.isfinite(value) and value >= 0.0 for value in values):
        raise ValueError("latency values must be finite and non-negative")
    result = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model_id": arguments.model_id,
        "metric": arguments.column,
        "unit": "milliseconds",
        "sample_count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
        "range": max(values) - min(values),
        "variance_sample": statistics.variance(values) if len(values) > 1 else None,
        "standard_deviation_sample": statistics.stdev(values) if len(values) > 1 else None,
        "p05": percentile(values, 0.05),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "throughput_from_mean_fps": 1000.0 / statistics.fmean(values) if statistics.fmean(values) else None,
        "latency_csv_sha256": file_sha256(arguments.latency_csv),
        "tool_sha256": file_sha256(Path(__file__)),
        "limitations": [
            "Throughput is the reciprocal of mean single-image inference latency.",
            "This summary does not include preprocessing or postprocessing unless the selected source column does.",
        ],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
