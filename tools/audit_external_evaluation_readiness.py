#!/usr/bin/env python3
"""Fail-closed readiness audit for the two external evaluation sources."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checked_hash(root: Path, relative_path: str | None, expected: str | None) -> dict:
    if not relative_path:
        return {"status": "MISSING_PATH", "path": relative_path}
    path = root / relative_path
    if not path.is_file():
        return {"status": "MISSING_FILE", "path": relative_path}
    observed = sha256(path)
    return {
        "status": "PASS" if expected and observed == expected else "HASH_MISMATCH",
        "path": relative_path,
        "expected_sha256": expected,
        "observed_sha256": observed,
    }


def audit(
    registry: dict,
    root: Path,
    alignment_v2_path: Path | None = None,
    consolidated_path: Path | None = None,
) -> dict:
    sources = {source["source_id"]: source for source in registry.get("sources", [])}
    blockers: list[str] = []
    results: dict[str, dict] = {}

    fasdd = sources.get("fasdd_uav")
    if fasdd is None:
        blockers.append("fasdd_uav is absent from the source registry")
    else:
        license_pass = (
            fasdd.get("license_identifier") == "CC-BY-SA-4.0"
            and str(fasdd.get("license_audit_status", "")).startswith("PASS_")
            and bool(fasdd.get("license_evidence_path"))
        )
        acquired = str(fasdd.get("acquisition_status", "")).startswith("ACQUIRED")
        overlap_pass = fasdd.get("overlap_audit_status") == "PASS"
        manifest_ready = bool(fasdd.get("manifest_path"))
        gates = {
            "license": "PASS" if license_pass else "BLOCKED",
            "acquisition": "PASS" if acquired else "BLOCKED",
            "checksums_labels_decode": "PASS" if manifest_ready else "BLOCKED",
            "overlap": "PASS" if overlap_pass else "BLOCKED",
            "evaluation_manifest": "PASS" if manifest_ready and overlap_pass else "BLOCKED",
        }
        for gate, status in gates.items():
            if status != "PASS":
                blockers.append(f"fasdd_uav:{gate}")
        results["fasdd_uav"] = {
            "status": "READY" if all(value == "PASS" for value in gates.values()) else "BLOCKED",
            "gates": gates,
            "license_identifier": fasdd.get("license_identifier"),
            "dataset_record_version": fasdd.get("dataset_record_version"),
            "publisher_reported_total_bytes": fasdd.get("dataset_record_total_bytes"),
            "admission_status": fasdd.get("admission_status"),
        }

    mmodal = sources.get("mmodalfire_rgb")
    if mmodal is None:
        blockers.append("mmodalfire_rgb is absent from the source registry")
    else:
        archive = mmodal.get("archive", {})
        archive_path = root / str(mmodal.get("local_raw_root", "")) / str(
            archive.get("name", "")
        )
        archive_size_pass = archive_path.is_file() and archive_path.stat().st_size == archive.get("bytes")
        condition = mmodal.get("publisher_condition_table", {})
        condition_hash = checked_hash(
            root, condition.get("derived_table"), condition.get("derived_table_sha256")
        )
        decode_hash = checked_hash(
            root,
            mmodal.get("full_frame_decode_manifest"),
            mmodal.get("full_frame_decode_manifest_sha256"),
        )
        counts = mmodal.get("full_frame_decode_counts", {})
        decode_pass = (
            decode_hash["status"] == "PASS"
            and mmodal.get("full_frame_decode_status")
            == "PASS_28_OF_28_WITH_19_METADATA_COUNT_MISMATCHES"
            and counts.get("decoder_failures") == 0
            and counts.get("decoded_frames") == 2_974_209
        )
        overlap_pass = mmodal.get("overlap_audit_status") == "PASS"
        alignment_ready = condition.get("video_alignment_status") in {
            "PASS_PUBLISHER_TIMESTAMP_AND_VISUAL_CROSS_CHECK",
            "PASS_PUBLISHER_TIMESTAMP_CROSS_CHECK",
        }
        gates = {
            "license": "PASS" if mmodal.get("license_identifier") == "CC-BY-4.0" else "BLOCKED",
            "archive_presence_and_size": "PASS" if archive_size_pass else "BLOCKED",
            "recorded_archive_checksum": "PASS" if archive.get("verified_sha256") else "BLOCKED",
            "condition_register_hash": condition_hash["status"],
            "full_decode": "PASS" if decode_pass else "BLOCKED",
            "event_condition_alignment": "PASS" if alignment_ready else "BLOCKED",
            "overlap": "PASS" if overlap_pass else "BLOCKED",
            "evaluation_manifest": (
                "PASS" if alignment_ready and overlap_pass and mmodal.get("manifest_path") else "BLOCKED"
            ),
        }
        for gate, status in gates.items():
            if status != "PASS":
                blockers.append(f"mmodalfire_rgb:{gate}")
        supplemental = {}
        for name, path in (
            ("narrow_ocr", alignment_v2_path),
            ("cross_pass_consolidation", consolidated_path),
        ):
            if path is not None and path.is_file():
                data = json.loads(path.read_text(encoding="utf-8"))
                supplemental[name] = {
                    "path": str(path),
                    "sha256": sha256(path),
                    "status": data.get("status"),
                    "video_count": data.get("video_count"),
                    "video_progression_pass_count": data.get(
                        "video_progression_pass_count",
                        data.get("video_pass_count"),
                    ),
                }
        results["mmodalfire_rgb"] = {
            "status": "READY" if all(value == "PASS" for value in gates.values()) else "BLOCKED",
            "gates": gates,
            "archive_path": str(archive_path),
            "archive_expected_bytes": archive.get("bytes"),
            "archive_observed_bytes": archive_path.stat().st_size if archive_path.is_file() else None,
            "condition_register": condition_hash,
            "full_decode_manifest": decode_hash,
            "full_decode_counts": counts,
            "supplemental_alignment_attempts": supplemental,
            "admission_status": mmodal.get("admission_status"),
        }

    return {
        "schema_version": 1,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": "READY" if not blockers else "BLOCKED",
        "source_count": len(sources),
        "sources": results,
        "blockers": blockers,
        "claim_boundary": registry.get("claim_boundary"),
        "interpretation": (
            "Readiness concerns source admission only. It is not model evaluation and does "
            "not establish operational industrial reliability."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--registry", type=Path, default=ROOT / "config/external_evaluation_sources_v1.json"
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--alignment-v2", type=Path)
    parser.add_argument("--consolidated", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; readiness evidence is non-overwriting")
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    result = audit(registry, args.root, args.alignment_v2, args.consolidated)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
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
