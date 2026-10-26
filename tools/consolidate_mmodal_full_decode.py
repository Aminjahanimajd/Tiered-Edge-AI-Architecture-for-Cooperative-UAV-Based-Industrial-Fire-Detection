#!/usr/bin/env python3
"""Consolidate append-only MmodalFire decoder attempts into a frozen manifest."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from collections import Counter
from pathlib import Path

COMPLETE_STATUSES = {"PASS", "DECODE_PASS_METADATA_COUNT_MISMATCH"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_id(file_name: str) -> str:
    stem = Path(file_name).stem
    suffix = hashlib.sha256(file_name.encode("utf-8")).hexdigest()[:12]
    safe_stem = "".join(char if char.isalnum() or char in "-_" else "_" for char in stem)
    return f"{safe_stem[:80]}__{suffix}"


def matching_attempts(attempts_dir: Path, expected_sha256: str) -> list[tuple[Path, dict]]:
    result = []
    for path in sorted(attempts_dir.glob("attempt_*.json")):
        record = load_json(path)
        if record.get("source_sha256") == expected_sha256:
            result.append((path, record))
    return result


def select_completion(attempts: list[tuple[Path, dict]]) -> tuple[Path, dict] | None:
    completed = [item for item in attempts if item[1].get("status") in COMPLETE_STATUSES]
    return completed[-1] if completed else None


def build(
    *, inventory_path: Path, evidence_root: Path, decode_tool: Path, consolidator: Path
) -> tuple[dict, list[str]]:
    inventory = load_json(inventory_path)
    records = []
    errors = []
    for expected in sorted(inventory["records"], key=lambda row: row["file_name"]):
        attempts_dir = evidence_root / "records" / safe_id(expected["file_name"])
        attempts = matching_attempts(attempts_dir, expected["sha256"])
        completion = select_completion(attempts)
        attempt_refs = [
            {
                "path": str(path),
                "sha256": sha256(path),
                "status": record.get("status"),
                "started_utc": record.get("started_utc"),
            }
            for path, record in attempts
        ]
        row = {
            "file_name": expected["file_name"],
            "source_sha256": expected["sha256"],
            "reported_frame_count": expected.get("reported_frame_count"),
            "attempts": attempt_refs,
            "completion_status": "INCOMPLETE",
        }
        if completion is None:
            errors.append(f"no completed matching decode attempt: {expected['file_name']}")
        else:
            completion_path, completion_record = completion
            row.update({
                "completion_status": completion_record["status"],
                "completion_attempt": str(completion_path),
                "completion_attempt_sha256": sha256(completion_path),
                "decoded_frame_count": completion_record.get("decoded_frame_count"),
                "decoder": completion_record.get("decoder"),
            })
        records.append(row)

    statuses = Counter(row["completion_status"] for row in records)
    manifest = {
        "schema_version": 1,
        "manifest_id": "mmodalfire_full_decode_v1",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": "PASS" if not errors else "INCOMPLETE",
        "source_inventory": str(inventory_path),
        "source_inventory_sha256": sha256(inventory_path),
        "source_archive_sha256": inventory.get("source_archive_sha256"),
        "evidence_root": str(evidence_root),
        "decode_tool": str(decode_tool),
        "decode_tool_sha256": sha256(decode_tool),
        "consolidator": str(consolidator),
        "consolidator_sha256": sha256(consolidator),
        "video_count": len(records),
        "completion_status_counts": dict(sorted(statuses.items())),
        "reported_frame_total": sum(row.get("reported_frame_count") or 0 for row in records),
        "decoded_frame_total": sum(row.get("decoded_frame_count") or 0 for row in records),
        "records": records,
        "errors": errors,
        "interpretation": (
            "A metadata-count mismatch means the immutable MP4 decoded to end without an "
            "FFmpeg error but the number of decoded frames differed from nb_frames."
        ),
        "claim_boundary": "complete media-decode audit only; no detection result is implied",
    }
    return manifest, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--decode-tool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest, errors = build(
        inventory_path=args.inventory,
        evidence_root=args.evidence_root,
        decode_tool=args.decode_tool,
        consolidator=Path(__file__),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({
        "status": manifest["status"],
        "video_count": manifest["video_count"],
        "completion_status_counts": manifest["completion_status_counts"],
        "error_count": len(errors),
        "output": str(args.output),
    }))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
