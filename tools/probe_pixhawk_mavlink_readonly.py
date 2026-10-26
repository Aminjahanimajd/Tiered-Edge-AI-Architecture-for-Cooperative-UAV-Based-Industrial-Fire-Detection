#!/usr/bin/env python3
"""Receive MAVLink telemetry without transmitting vehicle commands."""

from __future__ import print_function

import argparse
import collections
import datetime
import json
import time

from pymavlink import mavutil


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="/dev/ttyTHS1")
    parser.add_argument("--baud", type=int, default=57600)
    parser.add_argument("--duration-seconds", type=float, default=20.0)
    args = parser.parse_args()

    started = time.monotonic()
    deadline = started + args.duration_seconds
    counts = collections.Counter()
    first_messages = {}

    connection = mavutil.mavlink_connection(
        args.device,
        baud=args.baud,
        autoreconnect=False,
        source_system=255,
    )
    try:
        while time.monotonic() < deadline:
            message = connection.recv_match(blocking=True, timeout=1.0)
            if message is None:
                continue
            message_type = message.get_type()
            counts[message_type] += 1
            if message_type not in first_messages:
                first_messages[message_type] = message.to_dict()
    finally:
        connection.close()

    heartbeat = first_messages.get("HEARTBEAT")
    result = {
        "schema_version": 1,
        "generated_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "safety_state": (
            "propellers_removed; receive-only probe; no MAVLink send or "
            "vehicle-command call"
        ),
        "device": args.device,
        "baud": args.baud,
        "duration_seconds": round(time.monotonic() - started, 3),
        "message_count": sum(counts.values()),
        "message_types": dict(counts),
        "first_heartbeat": heartbeat,
        "status": "PASS" if heartbeat is not None else "FAIL_NO_HEARTBEAT",
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if heartbeat is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
