#!/usr/bin/env python3
"""Preserve a user-confirmed physical/safety precondition as hashed evidence."""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--assertion", action="append", required=True)
    parser.add_argument("--source", default="user_confirmed_in_active_codex_session")
    arguments = parser.parse_args()
    output_directory = os.path.abspath(arguments.output_directory)
    os.makedirs(output_directory, exist_ok=True)
    record_id = uuid.uuid4().hex
    received_utc = utc_now()
    record = {
        "schema_version": 1,
        "record_id": record_id,
        "label": arguments.label,
        "evidence_type": "operator_assertion",
        "source": arguments.source,
        "received_utc": received_utc,
        "recorded_monotonic_ns": time.monotonic_ns(),
        "assertions": list(arguments.assertion),
        "verification_boundary": "operator-confirmed; not independently machine-verifiable",
    }
    record_hash = hashlib.sha256(canonical_json(record)).hexdigest()
    envelope = {"record": record, "record_sha256": record_hash}
    filename = "{}_operator_{}_{}.json".format(
        received_utc.replace(":", "").replace("-", ""),
        arguments.label.replace(" ", "_"),
        record_id[:8],
    )
    output_path = os.path.join(output_directory, filename)
    with open(output_path, "x", encoding="utf-8") as output:
        json.dump(envelope, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    print("EVIDENCE_PATH={}".format(output_path))
    print("EVIDENCE_RECORD_SHA256={}".format(record_hash))


if __name__ == "__main__":
    main()
