#!/usr/bin/env python3
"""Validate and summarize one current two-device ROS 2 round-trip trial."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def last_json_record(path: Path, expected_role: str) -> dict:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("role") == expected_role:
            return record
    raise ValueError(f"no {expected_role!r} JSON record in {path}")


def percentile(values: list[float], percentage: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentage / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> list[float]:
    if total <= 0:
        raise ValueError("Wilson interval requires a positive denominator")
    proportion = successes / total
    denominator = 1.0 + z * z / total
    centre = (proportion + z * z / (2.0 * total)) / denominator
    half = z * math.sqrt(
        proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)
    ) / denominator
    return [max(0.0, centre - half), min(1.0, centre + half)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--initiator", type=Path, required=True)
    parser.add_argument("--responder", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument(
        "--network-condition",
        default="SwarmNet laboratory network; no deliberate competing-load injection",
    )
    parser.add_argument(
        "--claim-boundary",
        default=(
            "Stationary, camera-free ROS 2/DDS alert-verdict communication on the "
            "observed SwarmNet condition; this is not flight, industrial-site, or "
            "loaded-network evidence."
        ),
    )
    args = parser.parse_args()
    if args.output_directory.exists():
        parser.error("output directory exists; analysis is non-overwriting")

    initiator = last_json_record(args.initiator, "initiator")
    responder = last_json_record(args.responder, "responder")
    identity_fields = ("experiment_id", "trial_id", "event_prefix")
    identity_matches = {
        field: initiator.get(field) == responder.get(field) for field in identity_fields
    }
    if not all(identity_matches.values()):
        raise ValueError(f"cross-device identity mismatch: {identity_matches}")

    samples = initiator["samples"]
    event_ids = [sample["event_id"] for sample in samples]
    responder_ids = responder["received_event_ids"]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("initiator event IDs are not unique")
    if set(event_ids) != set(responder_ids):
        raise ValueError("initiator and responder event sets differ")
    received = [sample for sample in samples if sample["received"]]
    rtts = [float(sample["round_trip_ms"]) for sample in received]
    if not rtts:
        raise ValueError("no round-trip samples")
    mismatched = [sample for sample in received if not sample["correlation_match"]]

    recomputed = {
        "n": len(rtts),
        "mean": statistics.mean(rtts),
        "median": statistics.median(rtts),
        "minimum": min(rtts),
        "maximum": max(rtts),
        "population_standard_deviation": statistics.pstdev(rtts),
        "p95": percentile(rtts, 95.0),
    }
    reported = initiator["rtt_summary_ms"]
    if any(abs(recomputed[key] - float(reported[key])) > 1e-9 for key in recomputed):
        raise ValueError("reported and recomputed RTT summaries differ")

    args.output_directory.mkdir(parents=True, exist_ok=False)
    csv_path = args.output_directory / "roundtrip_samples.csv"
    with csv_path.open("x", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(
            destination,
            fieldnames=(
                "sequence",
                "event_id",
                "sent_monotonic_ns",
                "received_monotonic_ns",
                "round_trip_ms",
                "correlation_match",
            ),
        )
        writer.writeheader()
        for sample in samples:
            writer.writerow({key: sample.get(key) for key in writer.fieldnames})

    requested = int(initiator["requested_count"])
    summary = {
        "schema_version": 1,
        "status": "PASS" if len(received) == requested and not mismatched else "FAIL",
        "experiment_id": initiator["experiment_id"],
        "trial_id": initiator["trial_id"],
        "network_condition": args.network_condition,
        "sample_unit": "one correlated HazardAlert-to-HazardVerdict round trip",
        "requested_count": requested,
        "received_count": len(received),
        "missing_count": requested - len(received),
        "correlation_mismatch_count": len(mismatched),
        "unexpected_event_count": len(initiator["unexpected_event_ids"]),
        "responder_duplicate_count": len(responder["duplicate_event_ids"]),
        "delivery_fraction": len(received) / requested,
        "delivery_fraction_wilson_95_ci": wilson(len(received), requested),
        "rtt_ms": recomputed,
        "identity_matches": identity_matches,
        "one_way_latency_claim_permitted": False,
        "claim_boundary": args.claim_boundary,
        "raw_evidence": {
            "initiator_path": str(args.initiator.resolve()),
            "initiator_sha256": sha256(args.initiator),
            "responder_path": str(args.responder.resolve()),
            "responder_sha256": sha256(args.responder),
        },
        "derived_evidence": {
            "samples_csv": csv_path.name,
            "samples_csv_sha256": sha256(csv_path),
        },
    }
    summary_path = args.output_directory / "roundtrip_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
