#!/usr/bin/env python3
"""Resumably decode every frame of the immutable MmodalFire RGB videos.

Each decoder invocation creates a new attempt record. Failed attempts are never
replaced, and a video is skipped only when a matching source hash already has a
successful attempt produced by the same FFmpeg version.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import time
from pathlib import Path


SCHEMA_VERSION = 1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_progress(stdout: str) -> dict[str, str]:
    """Return the final value observed for each FFmpeg progress key."""
    result: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def safe_id(file_name: str) -> str:
    stem = Path(file_name).stem
    suffix = hashlib.sha256(file_name.encode("utf-8")).hexdigest()[:12]
    safe_stem = "".join(char if char.isalnum() or char in "-_" else "_" for char in stem)
    return f"{safe_stem[:80]}__{suffix}"


def ffmpeg_version(executable: str) -> str:
    completed = subprocess.run(
        [executable, "-version"], check=False, text=True, capture_output=True
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "FFmpeg version query failed")
    return completed.stdout.splitlines()[0].strip()


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def prior_pass_exists(
    attempts_dir: Path, source_sha256: str, decoder_version: str
) -> bool:
    if not attempts_dir.exists():
        return False
    for path in sorted(attempts_dir.glob("attempt_*.json")):
        try:
            record = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if (
            record.get("status") in {"PASS", "DECODE_PASS_METADATA_COUNT_MISMATCH"}
            and record.get("source_sha256") == source_sha256
            and record.get("decoder", {}).get("version") == decoder_version
        ):
            return True
    return False


def classify_decode(
    *, returncode: int, hash_ok: bool, progress_complete: bool, frame_count_ok: bool
) -> str:
    if returncode != 0 or not hash_ok or not progress_complete:
        return "FAIL"
    if not frame_count_ok:
        return "DECODE_PASS_METADATA_COUNT_MISMATCH"
    return "PASS"


def unique_attempt_path(attempts_dir: Path, started_utc: str) -> Path:
    compact = started_utc.replace("-", "").replace(":", "").replace("+00:00", "Z")
    candidate = attempts_dir / f"attempt_{compact}.json"
    counter = 1
    while candidate.exists():
        candidate = attempts_dir / f"attempt_{compact}_{counter:02d}.json"
        counter += 1
    return candidate


def write_exclusive_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, ensure_ascii=False)
        stream.write("\n")


def decode_one(
    *,
    path: Path,
    expected: dict,
    ffmpeg: str,
    decoder_version: str,
    output_root: Path,
) -> tuple[dict, Path]:
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")
    source_hash = sha256(path)
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-progress",
        "pipe:1",
        "-nostats",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-fps_mode",
        "passthrough",
        "-f",
        "null",
        "-",
    ]
    start_monotonic = time.monotonic()
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    elapsed = time.monotonic() - start_monotonic
    progress = parse_progress(completed.stdout)
    decoded_frames = int(progress["frame"]) if progress.get("frame", "").isdigit() else None
    expected_frames = expected.get("reported_frame_count")
    hash_ok = source_hash == expected.get("sha256")
    frame_count_ok = expected_frames is None or decoded_frames == expected_frames
    progress_complete = progress.get("progress") == "end"
    status = classify_decode(
        returncode=completed.returncode,
        hash_ok=hash_ok,
        progress_complete=progress_complete,
        frame_count_ok=frame_count_ok,
    )
    record = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "started_utc": started,
        "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds"),
        "elapsed_seconds": elapsed,
        "source_file_name": path.name,
        "source_bytes": path.stat().st_size,
        "source_sha256": source_hash,
        "expected_sha256": expected.get("sha256"),
        "source_hash_matches_inventory": hash_ok,
        "reported_frame_count": expected_frames,
        "decoded_frame_count": decoded_frames,
        "decoded_frame_count_matches_inventory": frame_count_ok,
        "progress_reached_end": progress_complete,
        "returncode": completed.returncode,
        "decoder": {"executable": ffmpeg, "version": decoder_version},
        "command": command,
        "stderr": completed.stderr,
        "progress_final": progress,
        "acceptance_rule": (
            "FAIL unless return code is zero, source SHA-256 matches the frozen inventory, "
            "and FFmpeg reports progress=end; classify a successful decode whose decoded "
            "frame count differs from container metadata as DECODE_PASS_METADATA_COUNT_MISMATCH"
        ),
        "claim_boundary": "media decodability only; this is not model evaluation",
    }
    attempts_dir = output_root / "records" / safe_id(path.name)
    attempt_path = unique_attempt_path(attempts_dir, started)
    write_exclusive_json(attempt_path, record)
    return record, attempt_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--video-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--file-name",
        action="append",
        help="decode only this inventory file name; repeat to select more than one",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")

    inventory = load_json(args.inventory)
    version = ffmpeg_version(args.ffmpeg)
    records = sorted(inventory["records"], key=lambda row: row["file_name"])
    if args.file_name:
        requested = set(args.file_name)
        known = {row["file_name"] for row in records}
        unknown = sorted(requested - known)
        if unknown:
            parser.error(f"file name not present in inventory: {unknown}")
        records = [row for row in records if row["file_name"] in requested]
    selected: list[dict] = []
    skipped: list[str] = []
    for expected in records:
        attempts_dir = args.output_root / "records" / safe_id(expected["file_name"])
        if prior_pass_exists(attempts_dir, expected["sha256"], version):
            skipped.append(expected["file_name"])
            continue
        selected.append(expected)
        if args.limit is not None and len(selected) >= args.limit:
            break

    run_started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds")
    outcomes = []
    for expected in selected:
        path = args.video_root / expected["file_name"]
        if not path.is_file():
            raise FileNotFoundError(path)
        record, attempt_path = decode_one(
            path=path,
            expected=expected,
            ffmpeg=args.ffmpeg,
            decoder_version=version,
            output_root=args.output_root,
        )
        outcomes.append({
            "file_name": expected["file_name"],
            "status": record["status"],
            "attempt_record": str(attempt_path),
            "decoded_frame_count": record["decoded_frame_count"],
            "elapsed_seconds": record["elapsed_seconds"],
        })
        print(json.dumps(outcomes[-1], ensure_ascii=False), flush=True)

    failed = any(row["status"] == "FAIL" for row in outcomes)
    warned = any(row["status"] == "DECODE_PASS_METADATA_COUNT_MISMATCH" for row in outcomes)
    run_status = "FAIL" if failed else ("PASS_WITH_WARNINGS" if warned else "PASS")
    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_started_utc": run_started,
        "run_finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds"),
        "inventory": str(args.inventory),
        "video_root": str(args.video_root),
        "decoder": {"executable": args.ffmpeg, "version": version},
        "selected_count": len(selected),
        "previously_passed_skipped_count": len(skipped),
        "previously_passed_skipped": skipped,
        "outcomes": outcomes,
        "status": run_status,
    }
    run_path = unique_attempt_path(args.output_root / "runs", run_started)
    write_exclusive_json(run_path, summary)
    print(json.dumps({"run_record": str(run_path), "status": summary["status"]}))
    return 1 if summary["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
