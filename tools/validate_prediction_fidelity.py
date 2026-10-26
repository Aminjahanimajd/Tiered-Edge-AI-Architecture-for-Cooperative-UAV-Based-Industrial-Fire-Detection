#!/usr/bin/env python3
"""Apply the frozen deployment-fidelity gate to two COCO prediction files."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

from validate_yolo_onnx_fidelity import match_predictions


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--native-predictions", type=Path, required=True)
    parser.add_argument("--converted-predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--converted-artifact", type=Path, required=True)
    parser.add_argument("--preprocessing", required=True)
    parser.add_argument("--decoding", required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    native_path = args.native_predictions.resolve()
    converted_path = args.converted_predictions.resolve()
    artifact = args.converted_artifact.resolve()
    comparison = match_predictions(
        json.loads(native_path.read_text(encoding="utf-8")),
        json.loads(converted_path.read_text(encoding="utf-8")),
        0.5,
    )
    confidence = comparison["mean_absolute_confidence_difference"]
    passed = (
        comparison["detection_match_rate"] >= 0.95
        and confidence is not None
        and confidence <= 0.02
    )
    record = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model_id": args.model_id,
        "status": "PASS" if passed else "FIDELITY_FAILED",
        "native_predictions_sha256": sha256(native_path),
        "converted_predictions_sha256": sha256(converted_path),
        "converted_artifact_sha256": sha256(artifact),
        "comparison": {
            **comparison,
            "minimum_match_rate": 0.95,
            "maximum_mean_absolute_confidence_difference": 0.02,
        },
        "preprocessing": args.preprocessing,
        "decoding": args.decoding,
        "class_mapping": "zero-based detector class plus one to COCO category ID",
        "claim_boundary": (
            "Laptop conversion-fidelity comparison only; this is not an exact-device "
            "deployment, latency, resource, or sustainability result."
        ),
        "generator_sha256": sha256(Path(__file__)),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
