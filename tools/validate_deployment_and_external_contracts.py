#!/usr/bin/env python3
"""Validate deployment preparation and external-data admission contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_IDS = {
    "yolov8n_416", "yolov8n_640", "yolov8s_416", "yolov8s_640",
    "ssd_mobilenet_v2_fpnlite_320", "efficientdet_lite0_320",
}
OUTCOMES = {
    "DEPLOYED", "TOO_SLOW", "OUT_OF_MEMORY", "CONVERSION_FAILED",
    "RUNTIME_UNSUPPORTED", "FIDELITY_FAILED",
}
PLATFORMS = {"sentinel_jetson_nano", "scout_voxl2"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate(deployment: dict, external: dict, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    if set(deployment.get("deployment_outcomes", [])) != OUTCOMES:
        errors.append("deployment outcome vocabulary differs from frozen set")
    calibration_path = root / str(deployment.get("canonical_calibration_evidence", ""))
    if not calibration_path.is_file():
        errors.append("canonical native calibration evidence is missing")
    elif sha256(calibration_path) != deployment.get(
        "canonical_calibration_evidence_sha256"
    ):
        errors.append("canonical native calibration evidence hash mismatch")
    models = deployment.get("models", [])
    ids = {model.get("model_id") for model in models}
    if ids != MODEL_IDS or len(models) != len(MODEL_IDS):
        errors.append("deployment registry must contain each of the six models once")
    for model in models:
        if not str(model.get("training_status", "")).startswith("completed"):
            errors.append(f"{model.get('model_id')}: training status is not completed")
        attempts = model.get("platform_attempts", {})
        if set(attempts) != PLATFORMS:
            errors.append(f"{model.get('model_id')}: platform matrix is incomplete")
        for platform, attempt in attempts.items():
            if attempt is not None and attempt.get("outcome") not in OUTCOMES:
                errors.append(f"{model.get('model_id')}/{platform}: invalid outcome")
        for artifact in model.get("native_artifacts", []):
            path = root / artifact["path"]
            if not path.is_file():
                errors.append(f"{model.get('model_id')}: missing {artifact['path']}")
            elif sha256(path) != artifact.get("sha256"):
                errors.append(f"{model.get('model_id')}: hash mismatch {artifact['path']}")
    fidelity = deployment.get("fidelity_protocol", {})
    if not fidelity.get("native_predictions_required"):
        errors.append("native calibration predictions must be required")
    if fidelity.get("minimum_detection_match_rate", 0) < 0.95:
        errors.append("fidelity match-rate tolerance was weakened")

    if external.get("training_use_permitted") is not False:
        errors.append("external sources must never be enabled for training")
    if external.get("raw_sources_are_immutable") is not True:
        errors.append("external raw sources must be immutable")
    source_ids = {source.get("source_id") for source in external.get("sources", [])}
    if source_ids != {"fasdd_uav", "mmodalfire_rgb"}:
        errors.append("external source registry is incomplete")
    for source in external.get("sources", []):
        if source.get("admission_status") == "ADMITTED":
            for key in ("license_identifier", "license_evidence_path", "manifest_path"):
                if not source.get(key):
                    errors.append(f"{source.get('source_id')}: admitted without {key}")
            if source.get("overlap_audit_status") != "PASS":
                errors.append(f"{source.get('source_id')}: admitted without overlap pass")
        if source.get("source_id") == "mmodalfire_rgb":
            condition = source.get("publisher_condition_table", {})
            table_path = root / str(condition.get("derived_table", ""))
            if not table_path.is_file():
                errors.append("mmodalfire_rgb: missing publisher condition table")
            elif sha256(table_path) != condition.get("derived_table_sha256"):
                errors.append("mmodalfire_rgb: publisher condition table hash mismatch")
            alignment_status = condition.get("video_alignment_status")
            allowed_alignment_statuses = {
                "REQUIRES_TIMESTAMP_ALIGNMENT_PER_PUBLISHER_README",
                "OCR_REVIEW_REQUIRED_BEFORE_INTERVAL_ADMISSION",
            }
            if alignment_status not in allowed_alignment_statuses:
                errors.append("mmodalfire_rgb: video alignment status was overstated")
            if alignment_status == "OCR_REVIEW_REQUIRED_BEFORE_INTERVAL_ADMISSION":
                for key, hash_key in (
                    ("alignment_frame_manifest", "alignment_frame_manifest_sha256"),
                    ("alignment_ocr_manifest", "alignment_ocr_manifest_sha256"),
                    (
                        "alignment_narrow_ocr_manifest",
                        "alignment_narrow_ocr_manifest_sha256",
                    ),
                    (
                        "alignment_cross_pass_manifest",
                        "alignment_cross_pass_manifest_sha256",
                    ),
                ):
                    evidence_path = root / str(condition.get(key, ""))
                    if not evidence_path.is_file():
                        errors.append(f"mmodalfire_rgb: missing {key}")
                    elif sha256(evidence_path) != condition.get(hash_key):
                        errors.append(f"mmodalfire_rgb: {key} hash mismatch")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--deployment", type=Path,
        default=ROOT / "config/model_deployment_registry_v1.json",
    )
    parser.add_argument(
        "--external", type=Path,
        default=ROOT / "config/external_evaluation_sources_v1.json",
    )
    args = parser.parse_args()
    deployment = json.loads(args.deployment.read_text(encoding="utf-8"))
    external = json.loads(args.external.read_text(encoding="utf-8"))
    errors = validate(deployment, external)
    print(json.dumps({
        "status": "PASS" if not errors else "FAIL",
        "model_count": len(deployment["models"]),
        "external_source_count": len(external["sources"]),
        "errors": errors,
    }, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
