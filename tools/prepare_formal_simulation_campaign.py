#!/usr/bin/env python3
"""Expand the preregistered M8 campaign into an immutable run plan."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
import audit_formal_simulation_readiness as readiness  # noqa: E402


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_seed(base_seed, campaign_id, stratum, fault, repetition):
    payload = "|".join(
        (str(base_seed), campaign_id, stratum, fault, str(repetition))
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")


def run_id(campaign_id, stratum, fault, repetition):
    label = fault if stratum == "fault" else stratum
    return f"{campaign_id}__{label}__r{repetition:03d}"


def build_plan(campaign, project):
    campaign_id = campaign["campaign_id"]
    base_seed = campaign["base_seed"]
    visual = campaign["visual_capture_policy"]
    rows = []

    for stratum, definition in campaign["run_strata"].items():
        selected = set(visual[f"{stratum}_repetitions"])
        for repetition in range(1, int(definition["count"]) + 1):
            fault = definition["fault"]
            rows.append({
                "run_id": run_id(campaign_id, stratum, fault, repetition),
                "stratum": stratum,
                "fault": fault,
                "event_id": definition["event_id"],
                "runner_mode": definition["runner_mode"],
                "repetition": repetition,
                "seed": stable_seed(
                    base_seed, campaign_id, stratum, fault, repetition
                ),
                "capture_visual": repetition in selected,
                "attempt": 1,
            })

    selected_fault_repetitions = set(visual["fault_repetitions"])
    count_per_fault = int(campaign["fault_stratum"]["count_per_fault"])
    for fault in project["simulation"]["faults"]:
        for repetition in range(1, count_per_fault + 1):
            rows.append({
                "run_id": run_id(campaign_id, "fault", fault, repetition),
                "stratum": "fault",
                "fault": fault,
                "event_id": campaign["fault_stratum"]["event_id"],
                "runner_mode": campaign["fault_stratum"]["runner_mode"],
                "repetition": repetition,
                "seed": stable_seed(
                    base_seed, campaign_id, "fault", fault, repetition
                ),
                "capture_visual": repetition in selected_fault_repetitions,
                "attempt": 1,
            })

    rows.sort(key=lambda row: hashlib.sha256(row["run_id"].encode()).hexdigest())
    return rows


def validate_plan(rows, campaign, project):
    errors = []
    identifiers = [row["run_id"] for row in rows]
    seeds = [row["seed"] for row in rows]
    expected = readiness.planned_counts(project)["total"]
    if len(rows) != expected:
        errors.append(f"run count {len(rows)} differs from expected {expected}")
    if len(identifiers) != len(set(identifiers)):
        errors.append("run identifiers are not unique")
    if len(seeds) != len(set(seeds)):
        errors.append("deterministic run seeds are not unique")
    known_faults = set(project["simulation"]["faults"]) | {"none"}
    unknown = sorted({row["fault"] for row in rows} - known_faults)
    if unknown:
        errors.append("plan contains unknown faults: " + ", ".join(unknown))
    visual_count = sum(bool(row["capture_visual"]) for row in rows)
    expected_visual = sum(
        len(campaign["visual_capture_policy"][f"{name}_repetitions"])
        for name in campaign["run_strata"]
    ) + (
        len(project["simulation"]["faults"])
        * len(campaign["visual_capture_policy"]["fault_repetitions"])
    )
    if visual_count != expected_visual:
        errors.append(
            f"visual run count {visual_count} differs from expected {expected_visual}"
        )
    return errors


def prepare(root, output_dir):
    root = Path(root).resolve()
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        raise FileExistsError(output_dir)
    campaign_path = root / "config/formal_simulation_campaign_v1.json"
    project_path = root / "config/project_strengthening_v1.json"
    scenario_path = root / "config/simulation_scenarios_v2.json"
    campaign = load_json(campaign_path)
    project = load_json(project_path)
    readiness_result = readiness.audit(root)
    rows = build_plan(campaign, project)
    plan_errors = validate_plan(rows, campaign, project)
    output_dir.mkdir(parents=True)
    runs_path = output_dir / "planned_runs.jsonl"
    with runs_path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    counts = {}
    for row in rows:
        key = row["fault"] if row["stratum"] == "fault" else row["stratum"]
        counts[key] = counts.get(key, 0) + 1
    manifest = {
        "schema_version": 1,
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "campaign_id": campaign["campaign_id"],
        "status": "PLAN_READY" if not plan_errors else "PLAN_INVALID",
        "execution_authorized": readiness_result["status"] == "READY" and not plan_errors,
        "readiness_status": readiness_result["status"],
        "readiness_blockers": readiness_result.get("blockers", []),
        "plan_errors": plan_errors,
        "run_count": len(rows),
        "visual_capture_run_count": sum(row["capture_visual"] for row in rows),
        "counts": counts,
        "ordering": campaign["ordering"],
        "retry_policy": campaign["retry_policy"],
        "safety_state": "plan generation only; no simulator or physical command executed",
        "acceptance": (
            "exactly 310 uniquely identified and uniquely seeded rows with the "
            "preregistered stratum counts and deterministic visual selections"
        ),
        "claim_boundary": campaign["claim_boundary"],
        "input_sha256": {
            "campaign": sha256(campaign_path),
            "project": sha256(project_path),
            "scenario": sha256(scenario_path),
            "readiness_tool": sha256(root / "tools/audit_formal_simulation_readiness.py"),
            "planner": sha256(Path(__file__)),
        },
        "planned_runs_sha256": sha256(runs_path),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = prepare(args.root, args.output_dir)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest["status"] == "PLAN_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
