#!/usr/bin/env python3
"""Append one validated event to a controlled-trial ground-truth JSONL file."""

from __future__ import print_function

import argparse
import json
import os
import time
from datetime import datetime, timezone


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def monotonic_ns():
    function = getattr(time, "monotonic_ns", None)
    return function() if function else int(time.monotonic() * 1000000000)


def read_records(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def append(path, record, exclusive=False):
    mode = "x" if exclusive else "a"
    with open(path, mode, encoding="utf-8") as output:
        output.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("init", "start", "end", "complete"))
    parser.add_argument("--output", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--note", default="")
    parser.add_argument("--metadata-json", default="{}")
    args = parser.parse_args()
    path = os.path.abspath(args.output)
    records = read_records(path)
    event_types = [record["event_type"] for record in records]
    if args.command == "init":
        if records or os.path.exists(path):
            raise RuntimeError("ground-truth file already exists")
        metadata = json.loads(args.metadata_json)
        event_type = "TRIAL_STARTED"
        values = {"metadata": metadata}
    elif args.command == "start":
        if event_types != ["TRIAL_STARTED"]:
            raise RuntimeError("start requires exactly one TRIAL_STARTED record")
        event_type = "HAZARD_VISIBLE_START"
        values = {"note": args.note}
    elif args.command == "end":
        if not event_types or event_types[-1] != "HAZARD_VISIBLE_START":
            raise RuntimeError("end requires an active visible interval")
        event_type = "HAZARD_VISIBLE_END"
        values = {"note": args.note}
    else:
        if not event_types or event_types[-1] != "HAZARD_VISIBLE_END":
            raise RuntimeError("complete requires a closed visible interval")
        event_type = "TRIAL_COMPLETED"
        values = {"note": args.note}
    record = {
        "schema_version": 1,
        "sequence": len(records) + 1,
        "event_type": event_type,
        "experiment_id": args.experiment_id,
        "trial_id": args.trial_id,
        "condition": "fire",
        "wall_time_utc": now_utc(),
        "monotonic_ns": monotonic_ns(),
    }
    record.update(values)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    append(path, record, exclusive=args.command == "init")
    print(json.dumps(record, sort_keys=True))


if __name__ == "__main__":
    main()
