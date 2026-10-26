#!/usr/bin/env bash
# Execute the three fidelity-admitted Scout candidates under the frozen protocol.

set -uo pipefail

root=${1:-/home/root/device_screening_20260925_r1}
output_root=${2:-/home/root/drone_enhanced_evidence/exact_device_screening_20260925_r1}
manifest="$root/config/deployment_calibration_manifest_v1.json"
images="$root/artifacts/training/fire_only_curated_v7_coco/valid/images"
tool="$root/tools/benchmark_exact_device_candidate.py"
manifest_sha=c4183ba0f550e38e7b66dd312a194601d60f7067e371546db40acf82992c0228
export PYTHONPATH="$root/src:$root/ros2_ws/src/drone_enhanced_nodes:${PYTHONPATH:-}"

if [ -e "$output_root" ]; then
  echo "refusing to overwrite $output_root" >&2
  exit 3
fi
mkdir -p "$output_root"
echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "safety_state=camera-free replay; no ROS, MAVLink, flight-controller, arm, or motor interface"
echo "protocol=64 images; 20 warm-ups; 200 measured; 1 Hz resources"

failures=0
run_candidate() {
  model_id=$1
  shift
  echo "candidate_started=$model_id utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  set +e
  python3 "$tool" "$@" \
    --model-id "$model_id" \
    --calibration-manifest "$manifest" \
    --expected-calibration-manifest-sha256 "$manifest_sha" \
    --image-root "$images" \
    --output-directory "$output_root/$model_id" \
    --formal \
    >"$output_root/${model_id}_console.log" 2>&1
  code=$?
  set -e
  echo "candidate_finished=$model_id exit_code=$code utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  cat "$output_root/${model_id}_console.log"
  if [ "$code" -ne 0 ]; then
    failures=$((failures + 1))
  fi
}

set -e
run_candidate yolov8n_416 \
  --backend onnx_yolo \
  --model "$root/artifacts/experiments/deployment_candidates_yolo_onnx_v1/yolov8n_416/source.onnx" \
  --expected-model-sha256 aefbc333350898a1be0e7c7e1fe1038722fbecb00ddc5b25f5d5f599ff473a80 \
  --onnx-provider CPUExecutionProvider

run_candidate yolov8s_416 \
  --backend onnx_yolo \
  --model "$root/artifacts/experiments/deployment_candidates_yolo_onnx_v1/yolov8s_416/source.onnx" \
  --expected-model-sha256 ef2fbce918f2109caa072f6aac30a49334ba68529ddec7cca21d2379f4e3e207 \
  --onnx-provider CPUExecutionProvider

run_candidate efficientdet_lite0_320 \
  --backend tflite_detection_postprocess \
  --model "$root/artifacts/experiments/model_screening_v1/efficientdet_lite0_screen_seed_20260729_retry10_resume_ckpt90/export_retry3_cpu/efficientdet_lite0.tflite" \
  --expected-model-sha256 948e71fa53fa9a740a2bca45f169280a9c6e6596a49bfcab65d0ad9cfda2f12c \
  --threads 4 \
  --boxes-tensor-index 598 \
  --classes-tensor-index 599 \
  --scores-tensor-index 600 \
  --count-tensor-index 601 \
  --class-id-offset 1 \
  --delegate-label tflite_runtime_default_cpu_delegate_unspecified

find "$output_root" -type f ! -name sha256_manifest.txt -print0 \
  | sort -z | xargs -0 sha256sum \
  >"$output_root/sha256_manifest.txt"
echo "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "candidate_failures=$failures"
if [ "$failures" -eq 0 ]; then
  echo "status=PASS_SCOUT_EXACT_DEVICE_SCREENING"
else
  echo "status=PARTIAL_SCOUT_EXACT_DEVICE_SCREENING"
fi
