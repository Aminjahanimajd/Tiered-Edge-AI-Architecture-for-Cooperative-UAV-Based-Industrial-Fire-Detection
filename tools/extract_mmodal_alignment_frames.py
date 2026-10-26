#!/usr/bin/env python3
"""Extract deterministic MmodalFire frames for timestamp and label alignment."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sample_times(duration_seconds: float) -> list[tuple[str, float]]:
    if duration_seconds <= 0:
        raise ValueError("duration must be positive")
    edge = min(5.0, duration_seconds / 4.0)
    candidates = [
        ("start", edge),
        ("middle", duration_seconds / 2.0),
        ("end", max(duration_seconds - edge, 0.0)),
    ]
    result: list[tuple[str, float]] = []
    used: set[float] = set()
    for label, value in candidates:
        rounded = round(value, 3)
        if rounded not in used:
            result.append((label, rounded))
            used.add(rounded)
    return result


def ffmpeg_version(executable: str) -> str:
    completed = subprocess.run(
        [executable, "-version"], check=False, text=True, capture_output=True
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "FFmpeg version query failed")
    return completed.stdout.splitlines()[0].strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--video-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    if args.output_root.exists():
        parser.error("output root already exists; extraction is non-overwriting")

    inventory_bytes = args.inventory.read_bytes()
    inventory = json.loads(inventory_bytes.decode("utf-8"))
    version = ffmpeg_version(args.ffmpeg)
    frames_root = args.output_root / "frames"
    frames_root.mkdir(parents=True)
    records = []
    any_failure = False
    for video in sorted(inventory["records"], key=lambda row: row["file_name"]):
        source = args.video_root / video["file_name"]
        if not source.is_file():
            raise FileNotFoundError(source)
        video_id = Path(video["file_name"]).stem
        for label, seconds in sample_times(float(video["duration_seconds"])):
            output = frames_root / f"{video_id}__{label}__{seconds:012.3f}s.png"
            command = [
                args.ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-v",
                "error",
                "-ss",
                f"{seconds:.3f}",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-vsync",
                "0",
                str(output),
            ]
            completed = subprocess.run(command, check=False, text=True, capture_output=True)
            status = "PASS" if completed.returncode == 0 and output.is_file() else "FAIL"
            any_failure |= status == "FAIL"
            records.append({
                "video_file_name": video["file_name"],
                "video_sha256": video["sha256"],
                "sample_label": label,
                "requested_offset_seconds": seconds,
                "status": status,
                "command": command,
                "returncode": completed.returncode,
                "stderr": completed.stderr,
                "output": str(output),
                "output_sha256": sha256(output) if output.is_file() else None,
                "output_bytes": output.stat().st_size if output.is_file() else None,
            })

    manifest = {
        "schema_version": 1,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "purpose": "deterministic visual frames for publisher timestamp and event-label alignment",
        "status": "FAIL" if any_failure else "PASS",
        "source_inventory": str(args.inventory),
        "source_inventory_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
        "decoder": {"executable": args.ffmpeg, "version": version},
        "sampling_rule": "min(5 s, duration/4), duration/2, duration-min(5 s, duration/4)",
        "record_count": len(records),
        "records": records,
        "claim_boundary": "alignment evidence only; sampled frames are not exhaustive overlap evidence",
    }
    manifest_path = args.output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": manifest["status"],
        "record_count": len(records),
        "manifest": str(manifest_path),
        "manifest_sha256": sha256(manifest_path),
    }))
    return 1 if any_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
