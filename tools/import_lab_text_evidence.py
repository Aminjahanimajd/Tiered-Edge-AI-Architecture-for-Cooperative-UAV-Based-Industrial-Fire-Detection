#!/usr/bin/env python3
"""Wrap a retained lab text log in a hashed evidence envelope."""

from __future__ import print_function

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--remote-command", required=True)
    arguments = parser.parse_args()

    input_path = os.path.abspath(arguments.input)
    with open(input_path, "rb") as source:
        raw = source.read()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        stdout = raw.decode("utf-16", errors="replace")
    elif raw[:512].count(b"\x00") > 16:
        stdout = raw.decode("utf-16-le", errors="replace")
    else:
        stdout = raw.decode("utf-8", errors="replace")
    record = {
        "schema_version": 1,
        "label": arguments.label,
        "device": arguments.device,
        "target": "lab_device",
        "authentication": "sshpass_operator_authorized",
        "host_key_checking": "disabled_for_isolated_swarmnet_lab_session",
        "remote_command": arguments.remote_command,
        "started_utc": utc_now(),
        "finished_utc": utc_now(),
        "elapsed_monotonic_ns": None,
        "timeout_seconds": None,
        "timed_out": False,
        "exit_code": 0,
        "stdout": stdout,
        "stderr": "",
        "imported_from_raw_log": os.path.basename(input_path),
        "raw_log_sha256": sha256_bytes(raw),
        "import_note": "Derived envelope; the referenced raw log remains authoritative.",
    }
    envelope = {"record": record, "record_sha256": sha256_bytes(canonical_json(record))}
    os.makedirs(arguments.output_directory, exist_ok=True)
    output_path = os.path.join(
        arguments.output_directory,
        "{}_{}.json".format(arguments.device, os.path.basename(input_path)),
    )
    with open(output_path, "x", encoding="utf-8") as output:
        json.dump(envelope, output, indent=2, sort_keys=True)
        output.write("\n")
    print(output_path)


if __name__ == "__main__":
    main()
