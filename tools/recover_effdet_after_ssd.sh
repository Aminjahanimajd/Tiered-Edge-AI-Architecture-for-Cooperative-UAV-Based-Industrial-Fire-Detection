#!/usr/bin/env bash
set -u

project=/mnt/d/Drones/Drone_Enhanced
experiment="$project/artifacts/experiments/model_screening_v1"
prior_events="$experiment/non_yolo_recovery_events.jsonl"
events="$experiment/effdet_recovery_events.jsonl"
logs="$experiment/queue_logs"

event() {
  printf '{"utc_time":"%s","model_id":"%s","event":"%s","exit_code":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "${3:-null}" >> "$events"
}

event efficientdet_lite0 waiting_for_ssd
while ! grep -q '"model_id":"ssd_mobilenet_v2","event":"training_retry_exited"' "$prior_events" 2>/dev/null; do
  sleep 30
done
while true; do
  temperature="$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | head -1 | tr -d ' ')"
  [[ "$temperature" =~ ^[0-9]+$ ]] && (( temperature < 65 )) && break
  sleep 20
done

source /home/sefroyek/.venvs/drone_enhanced_effdet_py39/bin/activate
export PYTHONPATH="$project/tools"
export TFHUB_CACHE_DIR="$project/artifacts/models/tfhub_cache"
nvidia_libs="$(find /home/sefroyek/.venvs/drone_enhanced_effdet_py39/lib/python3.9/site-packages/nvidia -type d -name lib | paste -sd:)"
export LD_LIBRARY_PATH="$nvidia_libs:${LD_LIBRARY_PATH:-}"
runner="$project/tools/run_effdet_experiment.py"
inputs=(
  --train-records "$project/artifacts/training/fire_only_curated_v7_tfrecord/coco_train.record-*"
  --train-annotations "$project/artifacts/training/fire_only_curated_v7_coco/train/labels.json"
  --validation-records "$project/artifacts/training/fire_only_curated_v7_tfrecord/coco_val.record-*"
  --validation-annotations "$project/artifacts/training/fire_only_curated_v7_coco/valid/labels.json"
  --batch-size 4
)

event efficientdet_lite0 fp32_sanity_started
python "$runner" "${inputs[@]}" \
  --output-directory "$experiment/efficientdet_lite0_sanity_retry2" --sanity \
  > "$logs/efficientdet_lite0_sanity_retry2.log" 2>&1
gate=$?
event efficientdet_lite0 fp32_sanity_exited "$gate"

if (( gate == 0 )); then
  event efficientdet_lite0 fp32_training_started
  python "$runner" "${inputs[@]}" \
    --output-directory "$experiment/efficientdet_lite0_screen_seed_20260729" \
    > "$logs/efficientdet_lite0_training_retry2.log" 2>&1
  event efficientdet_lite0 fp32_training_exited "$?"
else
  event efficientdet_lite0 fp32_training_not_admitted "$gate"
fi
event efficientdet_recovery completed
