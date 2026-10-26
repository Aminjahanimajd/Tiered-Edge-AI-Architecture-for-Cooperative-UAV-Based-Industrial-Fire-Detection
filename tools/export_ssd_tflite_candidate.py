#!/usr/bin/env python3
"""Export a frozen TF Object Detection SSD checkpoint to a TFLite candidate.

The output directory is append-only: an existing path is never overwritten.
Both the official exporter output and TFLite conversion diagnostics are kept so
that an unsupported conversion is evidence rather than a silently lost run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import subprocess
import sys
import time
import traceback
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}


def checkpoint_records(directory: Path) -> tuple[str, list[dict]]:
    import tensorflow as tf

    prefix_text = tf.train.latest_checkpoint(str(directory))
    if prefix_text is None:
        raise FileNotFoundError(f"no TensorFlow checkpoint found in {directory}")
    prefix = Path(prefix_text)
    files = sorted(prefix.parent.glob(prefix.name + ".*"))
    if not files:
        raise FileNotFoundError(f"checkpoint payload is missing for {prefix}")
    return str(prefix), [file_record(path) for path in files]


def write_text_exclusive(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipeline-config", type=Path, required=True)
    parser.add_argument("--checkpoint-directory", type=Path, required=True)
    parser.add_argument("--model-garden-research", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--max-detections", type=int, default=100)
    parser.add_argument("--ssd-use-regular-nms", action="store_true")
    args = parser.parse_args()

    import tensorflow as tf

    pipeline = args.pipeline_config.resolve()
    checkpoints = args.checkpoint_directory.resolve()
    research = args.model_garden_research.resolve()
    output = args.output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    started = time.monotonic()
    checkpoint_prefix, checkpoint_files = checkpoint_records(checkpoints)
    exporter = research / "object_detection" / "export_tflite_graph_tf2.py"
    if not exporter.is_file():
        raise FileNotFoundError(exporter)

    saved_model_output = output / "official_export"
    command = [
        sys.executable,
        str(exporter),
        f"--pipeline_config_path={pipeline}",
        f"--trained_checkpoint_dir={checkpoints}",
        f"--output_directory={saved_model_output}",
        f"--max_detections={args.max_detections}",
    ]
    if args.ssd_use_regular_nms:
        command.append("--ssd_use_regular_nms=true")
    summary = {
        "schema_version": 1,
        "access_class": "NO LAB",
        "model_id": "ssd_mobilenet_v2_fpnlite_320",
        "framework": "TensorFlow Object Detection API",
        "status": "running",
        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "python": platform.python_version(),
        "tensorflow": tf.__version__,
        "conversion": "float32_no_optimization",
        "max_detections": args.max_detections,
        "ssd_use_regular_nms": args.ssd_use_regular_nms,
        "pipeline_config": file_record(pipeline),
        "checkpoint_prefix": checkpoint_prefix,
        "checkpoint_files": checkpoint_files,
        "official_exporter": file_record(exporter),
        "official_exporter_command": command,
    }
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        write_text_exclusive(output / "official_export_stdout.log", result.stdout)
        write_text_exclusive(output / "official_export_stderr.log", result.stderr)
        summary["official_export_returncode"] = result.returncode
        if result.returncode != 0:
            raise RuntimeError(f"official exporter returned {result.returncode}")

        saved_model = saved_model_output / "saved_model"
        if not (saved_model / "saved_model.pb").is_file():
            raise FileNotFoundError(f"exporter did not create {saved_model / 'saved_model.pb'}")
        summary["saved_model_pb"] = file_record(saved_model / "saved_model.pb")

        converter = tf.lite.TFLiteConverter.from_saved_model(str(saved_model))
        candidate = converter.convert()
        tflite_path = output / "ssd_mobilenet_v2_fpnlite_320_float32.tflite"
        with tflite_path.open("xb") as stream:
            stream.write(candidate)
        summary["tflite_artifact"] = file_record(tflite_path)
        summary["status"] = "completed"
    except Exception as error:
        summary["status"] = "failed"
        summary["error"] = repr(error)
        summary["traceback"] = traceback.format_exc()
        raise
    finally:
        summary["ended_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        summary["elapsed_seconds"] = time.monotonic() - started
        with (output / "export_summary.json").open("x", encoding="utf-8") as stream:
            json.dump(summary, stream, indent=2, sort_keys=True)
            stream.write("\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
