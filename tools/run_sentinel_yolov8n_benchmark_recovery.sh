#!/usr/bin/env bash
set -uo pipefail

# Benchmark-only recovery for the already completed and hash-verified
# YOLOv8n-416 FP16 engine.  It must run after all TensorRT builds stop.

ROOT="${1:-/home/unime-nano/device_screening_20260925_r1}"
OUTPUT="$ROOT/exact_device_screening_20260928_r3_n416_benchmark"
ENGINE="$ROOT/engines/yolov8n_416/yolov8n_416_fp16.engine"
ENGINE_SHA="aa546ea6d7a7cc666f6b5a4c6a27974513ccad984b567e99394fff3dfd0020a8"
MANIFEST="$ROOT/config/deployment_calibration_manifest_v1.json"
MANIFEST_SHA="c4183ba0f550e38e7b66dd312a194601d60f7067e371546db40acf82992c0228"
IMAGES="$ROOT/artifacts/training/fire_only_curated_v7_coco/valid/images"
PYTHONPATH_VALUE="/home/unime-nano/restored_python_site_20260924/site-packages:$ROOT/src:$ROOT/ros2_ws/src/drone_enhanced_nodes"
TEGRASTATS="$(command -v tegrastats || true)"

if [[ -e "$OUTPUT" ]]; then
  echo "refusing to overwrite $OUTPUT" >&2
  exit 2
fi
mkdir -p "$OUTPUT"
if pgrep -f '[t]rtexec' >/dev/null; then
  echo "refusing to benchmark while TensorRT build is active" >"$OUTPUT/precondition_failure.log"
  exit 3
fi
observed="$(sha256sum "$ENGINE" | awk '{print $1}')"
if [[ "$observed" != "$ENGINE_SHA" ]]; then
  echo "engine hash mismatch: $observed" >"$OUTPUT/precondition_failure.log"
  exit 4
fi

command=(
  python3 "$ROOT/tools/benchmark_exact_device_candidate.py"
  --model-id yolov8n_416
  --backend tensorrt_yolo
  --model "$ENGINE"
  --expected-model-sha256 "$ENGINE_SHA"
  --calibration-manifest "$MANIFEST"
  --expected-calibration-manifest-sha256 "$MANIFEST_SHA"
  --image-root "$IMAGES"
  --output-directory "$OUTPUT/yolov8n_416"
  --formal
  --yolo-class-names fire
  --delegate-label CUDA_TensorRT_FP16
)
if [[ -n "$TEGRASTATS" ]]; then
  command+=(--tegrastats "$TEGRASTATS")
fi
PYTHONPATH="$PYTHONPATH_VALUE" "${command[@]}" >"$OUTPUT/yolov8n_416_benchmark_console.log" 2>&1
status=$?
printf '\nBENCHMARK_EXIT_CODE=%s\n' "$status" >>"$OUTPUT/yolov8n_416_benchmark_console.log"
(
  cd "$OUTPUT" || exit 1
  find . -type f ! -name sha256_manifest.txt -print0 | sort -z | xargs -0 sha256sum >sha256_manifest.txt
)
printf '%s\n' "SAFETY_STATE=camera-free replay; no ROS command, flight-controller, arm, or motor interface"
printf '%s\n' "RESULT_ROOT=$OUTPUT"
printf '%s\n' "OVERALL_EXIT_CODE=$status"
exit "$status"
