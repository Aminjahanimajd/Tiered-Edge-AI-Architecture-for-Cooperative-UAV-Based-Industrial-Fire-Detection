#!/usr/bin/env python3
"""Create or verify the frozen model-conversion calibration manifest."""

from __future__ import annotations

import argparse
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


def build(annotations: Path, images: Path, per_stratum: int = 32) -> dict:
    coco = json.loads(annotations.read_text(encoding="utf-8"))
    counts: dict[int, int] = {}
    classes: dict[int, set[int]] = {}
    for annotation in coco["annotations"]:
        image_id = int(annotation["image_id"])
        counts[image_id] = counts.get(image_id, 0) + 1
        classes.setdefault(image_id, set()).add(int(annotation["category_id"]))
    ordered = sorted(coco["images"], key=lambda item: (item["file_name"], int(item["id"])))
    positive = [item for item in ordered if counts.get(int(item["id"]), 0) > 0][:per_stratum]
    background = [item for item in ordered if counts.get(int(item["id"]), 0) == 0][:per_stratum]
    if len(positive) != per_stratum or len(background) != per_stratum:
        raise ValueError("validation split does not contain the requested balanced strata")
    records = []
    for stratum, selected in (("positive", positive), ("background", background)):
        for item in selected:
            image_id = int(item["id"])
            path = images / item["file_name"]
            if not path.is_file():
                raise FileNotFoundError(path)
            records.append({
                "stratum": stratum,
                "image_id": image_id,
                "file_name": item["file_name"],
                "width": int(item["width"]),
                "height": int(item["height"]),
                "annotation_count": counts.get(image_id, 0),
                "category_ids": sorted(classes.get(image_id, set())),
                "sha256": sha256(path),
            })
    return {
        "schema_version": 1,
        "manifest_id": "deployment_calibration_manifest_v1",
        "source_split": "frozen validation; never test",
        "selection_method": "lexical file_name order; first 32 annotated and first 32 background images",
        "annotations_path": str(annotations.relative_to(ROOT)).replace("\\", "/"),
        "annotations_sha256": sha256(annotations),
        "image_root": str(images.relative_to(ROOT)).replace("\\", "/"),
        "positive_count": len(positive),
        "background_count": len(background),
        "image_count": len(records),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotations", type=Path, default=ROOT / "artifacts/training/fire_only_curated_v7_coco/valid/labels.json")
    parser.add_argument("--images", type=Path, default=ROOT / "artifacts/training/fire_only_curated_v7_coco/valid/images")
    parser.add_argument("--output", type=Path, default=ROOT / "config/deployment_calibration_manifest_v1.json")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    manifest = build(args.annotations.resolve(), args.images.resolve())
    serialized = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if args.verify:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != serialized:
            print(json.dumps({"status": "FAIL", "reason": "manifest missing or differs"}))
            return 1
        print(json.dumps({"status": "PASS", "image_count": manifest["image_count"]}))
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(serialized)
    print(json.dumps({"status": "CREATED", "output": str(args.output), "image_count": manifest["image_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
