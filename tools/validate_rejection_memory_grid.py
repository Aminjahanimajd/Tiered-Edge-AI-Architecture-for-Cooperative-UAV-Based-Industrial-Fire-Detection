#!/usr/bin/env python3
"""Evaluate the preregistered simulator rejection-memory parameter grid."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
from pathlib import Path

from drone_enhanced_core.aerial_mission import (
    LocalENU,
    MapRejectionMemory,
    ScenarioTarget,
)


NS_PER_SECOND = 1_000_000_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def target(event_id: str, target_id: str, row: dict) -> ScenarioTarget:
    now_ns = round(float(row["time_s"]) * NS_PER_SECOND)
    return ScenarioTarget(
        event_id,
        target_id,
        LocalENU(float(row["east_m"]), float(row["north_m"]), float(row.get("up_m", 0.0))),
        now_ns,
        NS_PER_SECOND,
    )


def evaluate_setting(config: dict, ttl_s: float, radius_m: float) -> dict:
    baseline = config["baseline_rejection"]
    memory = MapRejectionMemory(
        expiry_ns=round(float(ttl_s) * NS_PER_SECOND),
        radius_m=float(radius_m),
        override_consecutive_frames=int(config["override_consecutive_frames"]),
        override_confidence_increase=float(config["override_confidence_increase"]),
    )
    memory.record_rejection(
        target(baseline["event_id"], baseline["target_id"], baseline),
        baseline["confidence"],
        round(float(baseline["time_s"]) * NS_PER_SECOND),
    )

    confounders = []
    for index, row in enumerate(config["repeated_confounder_observations"], 1):
        result = memory.evaluate(
            target("repeat-{}".format(index), baseline["target_id"], row),
            row["confidence"],
            row["consecutive_frames"],
            round(float(row["time_s"]) * NS_PER_SECOND),
        )
        confounders.append({"index": index, "dispatch_allowed": result.allowed, "reason": result.reason})

    safety = []
    for index, row in enumerate(config["safety_observations"], 1):
        result = memory.evaluate(
            target("safety-{}".format(index), row["target_id"], row),
            row["confidence"],
            row["consecutive_frames"],
            round(float(row["time_s"]) * NS_PER_SECOND),
        )
        delay_s = 0.0 if result.allowed else None
        safety.append({
            "case": row["case"],
            "dispatch_allowed": result.allowed,
            "required": bool(row["must_dispatch"]),
            "additional_delay_s": delay_s,
            "reason": result.reason,
        })

    confounders_suppressed = all(not row["dispatch_allowed"] for row in confounders)
    safety_retained = all(
        row["dispatch_allowed"] == row["required"]
        and row["additional_delay_s"] is not None
        and row["additional_delay_s"] <= float(config["maximum_new_hazard_delay_s"])
        for row in safety
    )
    return {
        "ttl_s": float(ttl_s),
        "radius_m": float(radius_m),
        "repeated_confounders": confounders,
        "safety_observations": safety,
        "confounders_suppressed": confounders_suppressed,
        "safety_retained": safety_retained,
        "passes": confounders_suppressed and safety_retained,
    }


def run(config: dict) -> dict:
    results = [
        evaluate_setting(config, ttl, radius)
        for radius in config["candidate_radius_m"]
        for ttl in config["candidate_ttl_s"]
    ]
    passing = [row for row in results if row["passes"]]
    selected = min(passing, key=lambda row: (row["radius_m"], row["ttl_s"])) if passing else None
    return {
        "schema_version": 1,
        "run_type": "ros_independent_rejection_memory_grid",
        "evaluated_settings": len(results),
        "passing_settings": len(passing),
        "selected": (
            {"radius_m": selected["radius_m"], "ttl_s": selected["ttl_s"]}
            if selected else None
        ),
        "map_space_suppression_enabled": selected is not None,
        "results": results,
        "claim_boundary": (
            "Deterministic logic validation on preregistered local-ENU scenarios; "
            "no PX4, Gazebo, detector, network, or physical vehicle was used."
        ),
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "config" / "rejection_memory_validation_v1.json",
    )
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    result = run(config)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / "raw_grid.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest = {
            "schema_version": 1,
            "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": "PASS" if result["selected"] else "FAIL",
            "acceptance": config["selection_rule"],
            "config": str(args.config.relative_to(root)).replace("\\", "/"),
            "config_sha256": sha256(args.config),
            "implementation": "src/drone_enhanced_core/aerial_mission.py",
            "implementation_sha256": sha256(root / "src/drone_enhanced_core/aerial_mission.py"),
            "selected": result["selected"],
            "limitations": [result["claim_boundary"]],
        }
        (args.output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["selected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
