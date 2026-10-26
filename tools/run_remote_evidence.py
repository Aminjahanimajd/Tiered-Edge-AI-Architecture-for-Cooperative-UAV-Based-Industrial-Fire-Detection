#!/usr/bin/env python3
"""Execute one key-only SSH command and preserve a hashed JSON evidence record."""

from __future__ import print_function

import argparse
import base64
import binascii
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def console_safe_text(value, encoding):
    """Escape only characters that the active console cannot represent."""
    encoding = encoding or "utf-8"
    return value.encode(encoding, errors="backslashreplace").decode(encoding)


def decode_remote_command(encoded_command):
    """Decode a UTF-8 remote command passed through a shell-safe Base64 value."""
    try:
        raw_command = base64.b64decode(encoded_command, validate=True)
        return raw_command.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("invalid Base64-encoded UTF-8 remote command") from exc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--known-hosts", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    command_group = parser.add_mutually_exclusive_group(required=True)
    command_group.add_argument("remote_command", nargs="?")
    command_group.add_argument("--remote-command-base64")
    arguments = parser.parse_args()

    if arguments.remote_command_base64:
        try:
            remote_command = decode_remote_command(arguments.remote_command_base64)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        remote_command = arguments.remote_command

    output_directory = os.path.abspath(arguments.output_directory)
    os.makedirs(output_directory, exist_ok=True)
    record_id = uuid.uuid4().hex
    started_utc = utc_now()
    started_monotonic_ns = time.monotonic_ns()
    ssh_arguments = [
        "ssh",
        "-i",
        os.path.abspath(arguments.key),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "UserKnownHostsFile={}".format(os.path.abspath(arguments.known_hosts)),
        "{}@{}".format(arguments.user, arguments.host),
        remote_command,
    ]
    timed_out = False
    try:
        result = subprocess.run(
            ssh_arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace",
            timeout=arguments.timeout_seconds,
            check=False,
        )
        exit_code = result.returncode
        stdout = result.stdout or ""
        stderr = result.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        stderr += "\nremote evidence command timed out"
    finished_monotonic_ns = time.monotonic_ns()
    record = {
        "schema_version": 1,
        "record_id": record_id,
        "label": arguments.label,
        "device": arguments.device,
        "target": "{}@{}".format(arguments.user, arguments.host),
        "authentication": "dedicated_key_batch_mode",
        "host_key_checking": "strict_dedicated_known_hosts",
        "remote_command": remote_command,
        "started_utc": started_utc,
        "finished_utc": utc_now(),
        "elapsed_monotonic_ns": finished_monotonic_ns - started_monotonic_ns,
        "timeout_seconds": arguments.timeout_seconds,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
    }
    record_hash = hashlib.sha256(canonical_json(record)).hexdigest()
    envelope = {"record": record, "record_sha256": record_hash}
    safe_timestamp = started_utc.replace(":", "").replace("-", "")
    filename = "{}_{}_{}_{}.json".format(
        safe_timestamp,
        arguments.device,
        arguments.label.replace(" ", "_"),
        record_id[:8],
    )
    output_path = os.path.join(output_directory, filename)
    with open(output_path, "x", encoding="utf-8") as output:
        json.dump(envelope, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    print(console_safe_text(stdout, getattr(sys.stdout, "encoding", None)), end="")
    if stderr:
        print(
            console_safe_text(stderr, getattr(sys.stderr, "encoding", None)),
            file=sys.stderr,
            end="",
        )
    print("EVIDENCE_PATH={}".format(output_path))
    print("EVIDENCE_RECORD_SHA256={}".format(record_hash))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
