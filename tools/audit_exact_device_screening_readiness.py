#!/usr/bin/env python3
"""Audit formal six-model exact-device screening preparation."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_IDS = {
    "yolov8n_416",
    "yolov8n_640",
    "yolov8s_416",
    "yolov8s_640",
    "ssd_mobilenet_v2_fpnlite_320",
    "efficientdet_lite0_320",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_artifact(root: Path, artifact: dict) -> dict:
    path = root / artifact["path"]
    if not path.is_file():
        return {"path": artifact["path"], "status": "MISSING"}
    observed_hash = sha256(path)
    observed_bytes = path.stat().st_size
    expected_bytes = artifact.get("bytes")
    size_pass = expected_bytes is None or expected_bytes == observed_bytes
    return {
        "path": artifact["path"],
        "status": (
            "PASS"
            if observed_hash == artifact.get("sha256") and size_pass
            else "MISMATCH"
        ),
        "expected_sha256": artifact.get("sha256"),
        "observed_sha256": observed_hash,
        "expected_bytes": expected_bytes,
        "observed_bytes": observed_bytes,
    }


def audit(matrix: dict, project: dict, root: Path) -> dict:
    blockers: list[str] = []
    warnings: list[str] = []
    models = matrix.get("models", [])
    identifiers = {model.get("model_id") for model in models}
    if identifiers != MODEL_IDS or len(models) != len(MODEL_IDS):
        blockers.append("candidate matrix does not contain each frozen model exactly once")

    frozen = project.get("device_screening", {})
    for matrix_key, project_key in (
        ("warmup_inferences", "warmup_iterations"),
        ("measured_inferences", "measured_iterations"),
        ("resource_sample_interval_seconds", "resource_sample_interval_s"),
    ):
        if matrix.get(matrix_key) != frozen.get(project_key):
            blockers.append(f"{matrix_key} differs from the frozen project protocol")

    calibration = verify_artifact(
        root,
        {
            "path": matrix.get("calibration_manifest", ""),
            "sha256": matrix.get("calibration_manifest_sha256"),
        },
    )
    if calibration["status"] != "PASS":
        blockers.append("calibration manifest is missing or hash-mismatched")

    model_results = []
    valid_prepared = 0
    rejected_prepared = 0
    native_tflite = 0
    for model in models:
        model_id = model.get("model_id")
        artifacts = [model.get("native_artifact", {})]
        artifacts.extend(model.get("additional_native_artifacts", []))
        artifacts.extend(model.get("prepared_artifacts", []))
        verified = [verify_artifact(root, artifact) for artifact in artifacts]
        if any(item["status"] != "PASS" for item in verified):
            blockers.append(f"{model_id}: artifact integrity gate failed")
        for artifact in model.get("prepared_artifacts", []):
            if artifact.get("fidelity_status") == "PASS":
                valid_prepared += 1
            elif artifact.get("fidelity_status") == "FIDELITY_FAILED":
                rejected_prepared += 1
                for platform_key in ("sentinel_plan", "scout_plan"):
                    if "DO_NOT_BENCHMARK" not in str(model.get(platform_key, "")) and not (
                        platform_key == "sentinel_plan" and "BUILD_TENSORRT" in str(model.get(platform_key, ""))
                    ):
                        blockers.append(
                            f"{model_id}: rejected artifact is not excluded by {platform_key}"
                        )
        if model_id == "efficientdet_lite0_320":
            if model.get("native_artifact", {}).get("fidelity_status") == "NOT_APPLICABLE_NATIVE_TFLITE":
                native_tflite += 1
        model_results.append(
            {
                "model_id": model_id,
                "artifacts": verified,
                "sentinel_plan": model.get("sentinel_plan"),
                "scout_plan": model.get("scout_plan"),
            }
        )

    if valid_prepared != 2:
        blockers.append(f"expected two fidelity-valid converted artifacts, observed {valid_prepared}")
    if rejected_prepared != 3:
        blockers.append(f"expected three rejected converted artifacts, observed {rejected_prepared}")
    if native_tflite != 1:
        blockers.append("EfficientDet native TFLite status is missing")

    executor = root / "tools/benchmark_exact_device_candidate.py"
    if not executor.is_file():
        blockers.append("formal replay-capable exact-device executor is not implemented")
    device_states = {
        name: value.get("device_status")
        for name, value in matrix.get("platforms", {}).items()
    }
    if any(not str(value).startswith("READY") for value in device_states.values()):
        blockers.append("both physical edge devices are not yet marked READY")

    return {
        "schema_version": 1,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": "READY" if not blockers else "BLOCKED",
        "matrix_id": matrix.get("protocol_id"),
        "model_count": len(models),
        "calibration_manifest": calibration,
        "fidelity_valid_converted_artifact_count": valid_prepared,
        "fidelity_rejected_converted_artifact_count": rejected_prepared,
        "native_tflite_candidate_count": native_tflite,
        "models": model_results,
        "device_states": device_states,
        "executor_present": executor.is_file(),
        "blockers": blockers,
        "warnings": warnings,
        "claim_boundary": matrix.get("claim_boundary"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--matrix", type=Path, default=ROOT / "config/exact_device_screening_v1.json"
    )
    parser.add_argument(
        "--project", type=Path, default=ROOT / "config/project_strengthening_v1.json"
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; readiness evidence is non-overwriting")
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    project = json.loads(args.project.read_text(encoding="utf-8"))
    result = audit(matrix, project, args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "blocker_count": len(result["blockers"]),
                "output": str(args.output),
                "output_sha256": sha256(args.output),
            }
        )
    )
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
