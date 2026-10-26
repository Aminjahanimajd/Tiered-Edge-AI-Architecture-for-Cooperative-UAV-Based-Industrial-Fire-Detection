#!/usr/bin/env bash
# Recover only the two fire-only YOLO runs blocked by the original decoder class list.

set -euo pipefail

root=${1:-/home/root/device_screening_20260925_r1}
output_root=${2:-/home/root/drone_enhanced_evidence/exact_device_screening_20260925_r2_yolo_recovery}
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
echo "recovery_reason=original executor used two YOLO classes for fire-only five-channel outputs"
echo "completed EfficientDet run is intentionally not repeated"

for model_id in yolov8n_416 yolov8s_416; do
  case "$model_id" in
    yolov8n_416)
      model="$root/artifacts/experiments/deployment_candidates_yolo_onnx_v1/yolov8n_416/source.onnx"
      model_sha=aefbc333350898a1be0e7c7e1fe1038722fbecb00ddc5b25f5d5f599ff473a80
      ;;
    yolov8s_416)
      model="$root/artifacts/experiments/deployment_candidates_yolo_onnx_v1/yolov8s_416/source.onnx"
      model_sha=ef2fbce918f2109caa072f6aac30a49334ba68529ddec7cca21d2379f4e3e207
      ;;
  esac
  echo "candidate_started=$model_id utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  python3 "$tool" \
    --model-id "$model_id" \
    --backend onnx_yolo \
    --model "$model" \
    --expected-model-sha256 "$model_sha" \
    --calibration-manifest "$manifest" \
    --expected-calibration-manifest-sha256 "$manifest_sha" \
    --image-root "$images" \
    --output-directory "$output_root/$model_id" \
    --onnx-provider CPUExecutionProvider \
    --yolo-class-names fire \
    --formal \
    >"$output_root/${model_id}_console.log" 2>&1
  cat "$output_root/${model_id}_console.log"
  echo "candidate_finished=$model_id utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
done

find "$output_root" -type f ! -name sha256_manifest.txt -print0 \
  | sort -z | xargs -0 sha256sum \
  >"$output_root/sha256_manifest.txt"
echo "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "status=PASS_SCOUT_YOLO_RECOVERY"
