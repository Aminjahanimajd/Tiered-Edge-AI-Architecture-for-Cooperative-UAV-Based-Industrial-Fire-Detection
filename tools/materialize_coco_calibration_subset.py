#!/usr/bin/env python3
"""Materialize the preregistered calibration image IDs as a COCO annotation file."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build(source: dict, selected_ids: set[int]) -> dict:
    known_ids = {int(row["id"]) for row in source["images"]}
    missing = selected_ids - known_ids
    if missing:
        raise ValueError(f"calibration IDs absent from source COCO: {sorted(missing)}")
    result = {
        key: value
        for key, value in source.items()
        if key not in {"images", "annotations"}
    }
    result["images"] = [
        row for row in source["images"] if int(row["id"]) in selected_ids
    ]
    result["annotations"] = [
        row for row in source.get("annotations", []) if int(row["image_id"]) in selected_ids
    ]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibration-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = args.calibration_manifest.resolve()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repo = Path(__file__).resolve().parents[1]
    source_path = repo / manifest["annotations_path"]
    if sha256(source_path) != manifest["annotations_sha256"]:
        raise ValueError("source COCO hash differs from preregistered calibration manifest")
    selected_ids = {int(row["image_id"]) for row in manifest["records"]}
    if len(selected_ids) != int(manifest["image_count"]):
        raise ValueError("calibration manifest contains duplicate IDs or a count mismatch")
    subset = build(json.loads(source_path.read_text(encoding="utf-8")), selected_ids)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(subset, stream, separators=(",", ":"), sort_keys=True)
        stream.write("\n")
    print(json.dumps({
        "status": "PASS",
        "images": len(subset["images"]),
        "annotations": len(subset["annotations"]),
        "source_sha256": sha256(source_path),
        "output_sha256": sha256(output),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
