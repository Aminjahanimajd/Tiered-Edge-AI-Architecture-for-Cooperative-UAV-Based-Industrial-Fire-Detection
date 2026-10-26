#!/usr/bin/env bash
set -uo pipefail

# Build and screen only the two fidelity-valid YOLO-416 candidates on the
# Sentinel.  The working root must be isolated and pre-populated by the host.
# No camera, ROS command, flight-controller, arm, or motor interface is used.

ROOT="${1:-/home/unime-nano/device_screening_20260925_r1}"
MANIFEST="$ROOT/config/deployment_calibration_manifest_v1.json"
IMAGES="$ROOT/artifacts/training/fire_only_curated_v7_coco/valid/images"
TOOLS="$ROOT/tools"
OUTPUT="$ROOT/exact_device_screening_20260925_r1"
PYTHONPATH_VALUE="/home/unime-nano/restored_python_site_20260924/site-packages:$ROOT/src:$ROOT/ros2_ws/src/drone_enhanced_nodes"
TRTEXEC="/usr/src/tensorrt/bin/trtexec"
TEGRASTATS="$(command -v tegrastats || true)"
CALIBRATION_SHA="c4183ba0f550e38e7b66dd312a194601d60f7067e371546db40acf82992c0228"

if [[ -e "$OUTPUT" ]]; then
  echo "refusing to overwrite $OUTPUT" >&2
  exit 2
fi
mkdir -p "$OUTPUT"

overall=0
for model_id in yolov8n_416 yolov8s_416; do
  case "$model_id" in
    yolov8n_416)
      onnx_sha="aefbc333350898a1be0e7c7e1fe1038722fbecb00ddc5b25f5d5f599ff473a80"
      ;;
    yolov8s_416)
      onnx_sha="ef2fbce918f2109caa072f6aac30a49334ba68529ddec7cca21d2379f4e3e207"
      ;;
  esac
  model_root="$ROOT/engines/$model_id"
  onnx="$ROOT/artifacts/experiments/deployment_candidates_yolo_onnx_v1/$model_id/source.onnx"
  engine="$model_root/${model_id}_fp16.engine"
  build_log="$OUTPUT/${model_id}_trtexec_build.log"
  inspect_log="$OUTPUT/${model_id}_engine_metadata.json"
  benchmark_log="$OUTPUT/${model_id}_benchmark_console.log"
  run_output="$OUTPUT/$model_id"

  observed="$(sha256sum "$onnx" | awk '{print $1}')"
  if [[ "$observed" != "$onnx_sha" ]]; then
    printf '%s\n' "ONNX hash mismatch for $model_id: $observed" | tee "$build_log"
    overall=1
    continue
  fi

  mkdir -p "$model_root"
  "$TRTEXEC" \
    --onnx="$onnx" \
    --saveEngine="$engine" \
    --fp16 \
    --workspace=1024 \
    --verbose \
    >"$build_log" 2>&1
  build_status=$?
  if [[ $build_status -ne 0 || ! -s "$engine" ]]; then
    printf '\nBUILD_STATUS=CONVERSION_FAILED exit_code=%s\n' "$build_status" >>"$build_log"
    overall=1
    continue
  fi
  printf '\nBUILD_STATUS=PASS engine_sha256=%s\n' "$(sha256sum "$engine" | awk '{print $1}')" >>"$build_log"

  PYTHONPATH="$PYTHONPATH_VALUE" python3 "$TOOLS/inspect_tensorrt_engine.py" "$engine" >"$inspect_log" 2>&1
  inspect_status=$?
  if [[ $inspect_status -ne 0 ]]; then
    printf '\nINSPECTION_STATUS=FAIL exit_code=%s\n' "$inspect_status" >>"$inspect_log"
    overall=1
    continue
  fi

  engine_sha="$(sha256sum "$engine" | awk '{print $1}')"
  benchmark=(
    python3 "$TOOLS/benchmark_exact_device_candidate.py"
    --model-id "$model_id"
    --backend tensorrt_yolo
    --model "$engine"
    --expected-model-sha256 "$engine_sha"
    --calibration-manifest "$MANIFEST"
    --expected-calibration-manifest-sha256 "$CALIBRATION_SHA"
    --image-root "$IMAGES"
    --output-directory "$run_output"
    --formal
    --yolo-class-names fire
    --delegate-label CUDA_TensorRT_FP16
  )
  if [[ -n "$TEGRASTATS" ]]; then
    benchmark+=(--tegrastats "$TEGRASTATS")
  fi
  PYTHONPATH="$PYTHONPATH_VALUE" "${benchmark[@]}" >"$benchmark_log" 2>&1
  benchmark_status=$?
  printf '\nBENCHMARK_EXIT_CODE=%s\n' "$benchmark_status" >>"$benchmark_log"
  if [[ $benchmark_status -ne 0 ]]; then
    overall=1
  fi
done

(
  cd "$OUTPUT" || exit 1
  find . -type f -print0 | sort -z | xargs -0 sha256sum >sha256_manifest.txt
)
printf '%s\n' "SAFETY_STATE=camera-free replay; no ROS command, flight-controller, arm, or motor interface"
printf '%s\n' "RESULT_ROOT=$OUTPUT"
printf '%s\n' "OVERALL_EXIT_CODE=$overall"
exit "$overall"
