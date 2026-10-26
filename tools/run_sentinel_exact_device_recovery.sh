#!/usr/bin/env bash
set -uo pipefail

# Non-overwriting recovery after the 25 September user-requested pause.
# Reuses the completed, hash-verified YOLOv8n FP16 engine, then rebuilds only
# the interrupted YOLOv8s FP16 engine.  No camera or actuation path is used.

ROOT="${1:-/home/unime-nano/device_screening_20260925_r1}"
OUTPUT="$ROOT/exact_device_screening_20260928_r2_recovery"
MANIFEST="$ROOT/config/deployment_calibration_manifest_v1.json"
IMAGES="$ROOT/artifacts/training/fire_only_curated_v7_coco/valid/images"
TOOLS="$ROOT/tools"
PYTHONPATH_VALUE="/home/unime-nano/restored_python_site_20260924/site-packages:$ROOT/src:$ROOT/ros2_ws/src/drone_enhanced_nodes"
TRTEXEC="/usr/src/tensorrt/bin/trtexec"
TEGRASTATS="$(command -v tegrastats || true)"
CALIBRATION_SHA="c4183ba0f550e38e7b66dd312a194601d60f7067e371546db40acf82992c0228"
N_ENGINE="$ROOT/engines/yolov8n_416/yolov8n_416_fp16.engine"
N_ENGINE_SHA="aa546ea6d7a7cc666f6b5a4c6a27974513ccad984b567e99394fff3dfd0020a8"
S_ONNX="$ROOT/artifacts/experiments/deployment_candidates_yolo_onnx_v1/yolov8s_416/source.onnx"
S_ONNX_SHA="ef2fbce918f2109caa072f6aac30a49334ba68529ddec7cca21d2379f4e3e207"
S_ENGINE="$ROOT/engines/yolov8s_416/yolov8s_416_fp16_r2.engine"

if [[ -e "$OUTPUT" ]]; then
  echo "refusing to overwrite $OUTPUT" >&2
  exit 2
fi
mkdir -p "$OUTPUT"

run_benchmark() {
  local model_id="$1"
  local engine="$2"
  local expected_sha="$3"
  local run_output="$OUTPUT/$model_id"
  local console="$OUTPUT/${model_id}_benchmark_console.log"
  local command=(
    python3 "$TOOLS/benchmark_exact_device_candidate.py"
    --model-id "$model_id"
    --backend tensorrt_yolo
    --model "$engine"
    --expected-model-sha256 "$expected_sha"
    --calibration-manifest "$MANIFEST"
    --expected-calibration-manifest-sha256 "$CALIBRATION_SHA"
    --image-root "$IMAGES"
    --output-directory "$run_output"
    --formal
    --yolo-class-names fire
    --delegate-label CUDA_TensorRT_FP16
  )
  if [[ -n "$TEGRASTATS" ]]; then
    command+=(--tegrastats "$TEGRASTATS")
  fi
  PYTHONPATH="$PYTHONPATH_VALUE" "${command[@]}" >"$console" 2>&1
  local status=$?
  printf '\nBENCHMARK_EXIT_CODE=%s\n' "$status" >>"$console"
  return "$status"
}

overall=0
if [[ "$(sha256sum "$N_ENGINE" | awk '{print $1}')" != "$N_ENGINE_SHA" ]]; then
  echo "YOLOv8n engine hash mismatch" >"$OUTPUT/yolov8n_416_recovery_gate.log"
  overall=1
else
  printf '%s\n' "REUSED_COMPLETED_ENGINE_SHA256=$N_ENGINE_SHA" >"$OUTPUT/yolov8n_416_recovery_gate.log"
  run_benchmark yolov8n_416 "$N_ENGINE" "$N_ENGINE_SHA" || overall=1
fi

if [[ "$(sha256sum "$S_ONNX" | awk '{print $1}')" != "$S_ONNX_SHA" ]]; then
  echo "YOLOv8s ONNX hash mismatch" >"$OUTPUT/yolov8s_416_trtexec_build.log"
  overall=1
else
  mkdir -p "$(dirname "$S_ENGINE")"
  "$TRTEXEC" \
    --onnx="$S_ONNX" \
    --saveEngine="$S_ENGINE" \
    --fp16 \
    --workspace=1024 \
    --verbose \
    >"$OUTPUT/yolov8s_416_trtexec_build.log" 2>&1
  build_status=$?
  if [[ $build_status -ne 0 || ! -s "$S_ENGINE" ]]; then
    printf '\nBUILD_STATUS=CONVERSION_FAILED exit_code=%s\n' "$build_status" >>"$OUTPUT/yolov8s_416_trtexec_build.log"
    overall=1
  else
    s_engine_sha="$(sha256sum "$S_ENGINE" | awk '{print $1}')"
    printf '\nBUILD_STATUS=PASS engine_sha256=%s\n' "$s_engine_sha" >>"$OUTPUT/yolov8s_416_trtexec_build.log"
    PYTHONPATH="$PYTHONPATH_VALUE" python3 "$TOOLS/inspect_tensorrt_engine.py" "$S_ENGINE" \
      >"$OUTPUT/yolov8s_416_engine_metadata.json" 2>&1
    if [[ $? -ne 0 ]]; then
      overall=1
    else
      run_benchmark yolov8s_416 "$S_ENGINE" "$s_engine_sha" || overall=1
    fi
  fi
fi

(
  cd "$OUTPUT" || exit 1
  find . -type f ! -name sha256_manifest.txt -print0 | sort -z | xargs -0 sha256sum >sha256_manifest.txt
)
printf '%s\n' "SAFETY_STATE=camera-free replay; no ROS command, flight-controller, arm, or motor interface"
printf '%s\n' "RESULT_ROOT=$OUTPUT"
printf '%s\n' "OVERALL_EXIT_CODE=$overall"
exit "$overall"
