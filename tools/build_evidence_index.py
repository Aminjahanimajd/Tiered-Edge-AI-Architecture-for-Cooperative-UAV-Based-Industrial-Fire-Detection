#!/usr/bin/env python3
"""Verify raw evidence envelopes and create a compact reproducible index."""

from __future__ import print_function

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def evidence_status(record):
    """Summarize execution status without hiding successful commands' warnings."""
    exit_code = record.get("exit_code")
    if exit_code is None:
        return "ASSERTED"
    if exit_code != 0:
        return "FAIL"
    if record.get("stdout") is None or record.get("stderr") is None:
        return "INCOMPLETE"
    if record.get("stderr", "").strip():
        return "PASS_WITH_STDERR"
    return "PASS"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence_directory")
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    evidence_directory = os.path.abspath(arguments.evidence_directory)
    output_path = os.path.abspath(arguments.output)
    records = []
    for filename in sorted(os.listdir(evidence_directory)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(evidence_directory, filename)
        with open(path, "r", encoding="utf-8") as source:
            envelope = json.load(source)
        record = envelope["record"]
        calculated_record_hash = sha256_bytes(canonical_json(record))
        stored_record_hash = envelope["record_sha256"]
        if calculated_record_hash != stored_record_hash:
            raise ValueError("record hash mismatch: {}".format(filename))
        records.append(
            {
                "filename": filename,
                "file_sha256": sha256_file(path),
                "record_sha256": stored_record_hash,
                "record_id": record["record_id"],
                "label": record["label"],
                "device": record.get("device", "operator"),
                "started_or_received_utc": record.get(
                    "started_utc", record.get("received_utc")
                ),
                "exit_code": record.get("exit_code"),
                "status": evidence_status(record),
            }
        )
    index = {
        "schema_version": 1,
        "evidence_directory": evidence_directory,
        "generated_utc": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "record_count": len(records),
        "all_record_hashes_verified": True,
        "records": records,
    }
    parent = os.path.dirname(output_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(output_path, "x", encoding="utf-8") as output:
        json.dump(index, output, indent=2, sort_keys=True)
        output.write("\n")
    print("INDEX_PATH={}".format(output_path))
    print("INDEX_SHA256={}".format(sha256_file(output_path)))
    print("RECORD_COUNT={}".format(len(records)))


if __name__ == "__main__":
    main()
