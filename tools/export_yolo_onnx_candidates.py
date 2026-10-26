#!/usr/bin/env python3
"""Export the four frozen YOLO checkpoints to isolated ONNX candidates."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def candidates(registry: dict) -> list[dict]:
    result = []
    for model in registry["models"]:
        if model["native_framework"] != "ultralytics":
            continue
        artifact = model["native_artifacts"][0]
        result.append({
            "model_id": model["model_id"],
            "input_size": int(model["input_size"]),
            "source_path": artifact["path"],
            "source_sha256": artifact["sha256"],
        })
    return result


def run(registry_path: Path, output: Path, opset: int) -> dict:
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    rows = candidates(registry)
    if len(rows) != 4:
        raise ValueError(f"expected four Ultralytics candidates, found {len(rows)}")
    output.mkdir(parents=True)
    from ultralytics import YOLO
    import onnx
    import torch
    import ultralytics

    started = dt.datetime.now(dt.timezone.utc).isoformat()
    for row in rows:
        source = ROOT / row["source_path"]
        if not source.is_file() or sha256(source) != row["source_sha256"]:
            raise ValueError(f"source checkpoint mismatch: {source}")
        model_dir = output / row["model_id"]
        model_dir.mkdir()
        copied = model_dir / "source.pt"
        shutil.copy2(source, copied)
        exported = Path(YOLO(str(copied)).export(
            format="onnx",
            imgsz=row["input_size"],
            opset=opset,
            simplify=False,
            dynamic=False,
            half=False,
            batch=1,
            device="cpu",
        ))
        expected = model_dir / "source.onnx"
        if exported.resolve() != expected.resolve() or not expected.is_file():
            raise RuntimeError(f"unexpected ONNX export path: {exported}")
        graph = onnx.load(str(expected))
        onnx.checker.check_model(graph)
        row.update({
            "copied_source_sha256": sha256(copied),
            "onnx_path": str(expected.relative_to(ROOT)).replace("\\", "/"),
            "onnx_sha256": sha256(expected),
            "onnx_bytes": expected.stat().st_size,
            "onnx_ir_version": int(graph.ir_version),
            "onnx_opset_imports": [
                {"domain": item.domain, "version": int(item.version)}
                for item in graph.opset_import
            ],
            "onnx_checker": "PASS",
            "fidelity_status": "PENDING_CANONICAL_CALIBRATION_COMPARISON",
            "jetson_status": "PENDING_EXACT_DEVICE_ATTEMPT",
            "voxl_status": "PENDING_EXACT_DEVICE_ATTEMPT",
        })
    manifest = {
        "schema_version": 1,
        "run_type": "isolated_yolo_onnx_deployment_candidate_export",
        "started_utc": started,
        "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "registry_path": str(registry_path.relative_to(ROOT)).replace("\\", "/"),
        "registry_sha256": sha256(registry_path),
        "configuration": {
            "format": "ONNX",
            "opset": opset,
            "batch": 1,
            "dynamic": False,
            "simplify": False,
            "half": False,
            "device": "CPU",
        },
        "software": {
            "python": platform.python_version(),
            "ultralytics": ultralytics.__version__,
            "torch": torch.__version__,
            "onnx": onnx.__version__,
        },
        "models": rows,
        "status": "EXPORT_COMPLETE_FIDELITY_AND_DEVICE_TESTS_PENDING",
        "claim_boundary": "Graph export and ONNX structural validation only; no conversion fidelity, device deployability, latency, or accuracy claim.",
        "generator_sha256": sha256(Path(__file__)),
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--registry", type=Path,
        default=ROOT / "config/model_deployment_registry_v1.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--opset", type=int, default=12)
    args = parser.parse_args(argv)
    if not 9 <= args.opset <= 21:
        parser.error("opset must be between 9 and 21")
    manifest = run(args.registry.resolve(), args.output.resolve(), args.opset)
    print(json.dumps({
        "status": manifest["status"],
        "models": len(manifest["models"]),
        "output": str(args.output.resolve()),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
