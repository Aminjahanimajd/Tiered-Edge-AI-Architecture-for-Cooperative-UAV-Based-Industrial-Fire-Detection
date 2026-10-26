#!/usr/bin/env python3
"""Run deterministic pre-ROS coordination fault scenarios."""

from __future__ import print_function

import argparse
import json

from drone_enhanced_core.simulation import replay_coordination


SCENARIOS = {
    "confirmed": [
        {
            "event_id": "simulated-event-1",
            "verdict": "CONFIRMED",
            "confidence": 0.9,
            "now_ns": 1500000000,
        }
    ],
    "rejected": [
        {
            "event_id": "simulated-event-1",
            "verdict": "REJECTED",
            "confidence": 0.1,
            "now_ns": 1500000000,
        }
    ],
    "error": [
        {
            "event_id": "simulated-event-1",
            "verdict": "ERROR",
            "confidence": 0.0,
            "now_ns": 1500000000,
            "reason": "stale_frame",
        }
    ],
    "timeout": [],
    "mismatch_then_confirmed": [
        {
            "event_id": "unrelated-event",
            "verdict": "REJECTED",
            "confidence": 0.1,
            "now_ns": 1300000000,
        },
        {
            "event_id": "simulated-event-1",
            "verdict": "CONFIRMED",
            "confidence": 0.9,
            "now_ns": 1500000000,
        },
    ],
    "late_confirmation": [
        {
            "event_id": "simulated-event-1",
            "verdict": "CONFIRMED",
            "confidence": 0.9,
            "now_ns": 2500000000,
        }
    ],
    "duplicate_confirmation": [
        {
            "event_id": "simulated-event-1",
            "verdict": "CONFIRMED",
            "confidence": 0.9,
            "now_ns": 1500000000,
        },
        {
            "event_id": "simulated-event-1",
            "verdict": "CONFIRMED",
            "confidence": 0.9,
            "now_ns": 1600000000,
        },
    ],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=sorted(SCENARIOS))
    parser.add_argument("--output")
    arguments = parser.parse_args()
    result = replay_coordination(SCENARIOS[arguments.scenario])
    payload = json.dumps(result, indent=2, sort_keys=True)
    if arguments.output:
        with open(arguments.output, "x", encoding="utf-8") as output:
            output.write(payload)
            output.write("\n")
    print(payload)


if __name__ == "__main__":
    main()
