#!/usr/bin/env python3
"""Inventory and structurally probe immutable MmodalFire video files."""

from __future__ import annotations

import argparse
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


def rate(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    numerator, denominator = value.split("/", 1)
    denominator_value = float(denominator)
    return None if denominator_value == 0 else float(numerator) / denominator_value


def probe(path: Path, ffprobe: str) -> dict:
    command = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames:format=duration",
        "-of", "json", str(path),
    ]
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    if completed.returncode != 0:
        return {
            "probe_status": "FAIL",
            "probe_returncode": completed.returncode,
            "probe_stderr": completed.stderr.strip(),
        }
    payload = json.loads(completed.stdout)
    streams = payload.get("streams", [])
    if len(streams) != 1:
        return {"probe_status": "FAIL", "probe_stderr": "expected one selected video stream"}
    stream = streams[0]
    return {
        "probe_status": "PASS",
        "codec": stream.get("codec_name"),
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "reported_frame_count": (
            int(stream["nb_frames"]) if str(stream.get("nb_frames", "")).isdigit() else None
        ),
        "nominal_fps": rate(stream.get("r_frame_rate")),
        "average_fps": rate(stream.get("avg_frame_rate")),
        "duration_seconds": float(payload.get("format", {}).get("duration", 0.0)),
    }


def build(video_root: Path, ffprobe: str) -> dict:
    paths = sorted(video_root.glob("*.mp4"), key=lambda path: path.name)
    if not paths:
        raise ValueError("no MP4 files found")
    records = []
    for path in paths:
        record = {
            "file_name": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
            "full_frame_decode_status": "NOT_RUN",
        }
        record.update(probe(path, ffprobe))
        records.append(record)
    return {
        "schema_version": 1,
        "manifest_id": "mmodalfire_media_inventory_v1",
        "source_doi": "10.6084/m9.figshare.28804448.v1",
        "source_archive_sha256": "e65d162d03005584ac6b765efc7a14dca3de3a94df9a3c6b9a27d79de3242fb1",
        "selection": "all MP4 files in the verified archive",
        "video_file_count": len(records),
        "structural_probe_pass_count": sum(row["probe_status"] == "PASS" for row in records),
        "full_frame_decode_complete": False,
        "records": records,
        "limitation": "ffprobe structural success is not full-frame decode validation",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()
    manifest = build(args.video_root, args.ffprobe)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({
        "status": "PASS" if manifest["structural_probe_pass_count"] == manifest["video_file_count"] else "FAIL",
        "video_file_count": manifest["video_file_count"],
        "structural_probe_pass_count": manifest["structural_probe_pass_count"],
        "output": str(args.output),
    }))
    return 0 if manifest["structural_probe_pass_count"] == manifest["video_file_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
