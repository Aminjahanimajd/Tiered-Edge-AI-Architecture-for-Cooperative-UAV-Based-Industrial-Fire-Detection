#!/usr/bin/env bash
set -u

project=/mnt/d/Drones/Drone_Enhanced
experiment="$project/artifacts/experiments/model_screening_v1"
events="$experiment/non_yolo_final_retry_events.jsonl"
log="$experiment/queue_logs/efficientdet_lite0_training_retry5.log"
sanity_log="$experiment/queue_logs/efficientdet_lite0_sanity_retry4.log"

event() {
  printf '{"utc_time":"%s","model_id":"%s","event":"%s","exit_code":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "${3:-null}" >> "$events"
}

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

inputs=(
  --train-records "$project/artifacts/training/fire_only_curated_v7_tfrecord_effdet_labels/coco_train.record-*" \
  --train-annotations "$project/artifacts/training/fire_only_curated_v7_coco/train/labels.json" \
  --validation-records "$project/artifacts/training/fire_only_curated_v7_tfrecord_effdet_labels/coco_val.record-*" \
  --validation-annotations "$project/artifacts/training/fire_only_curated_v7_coco/valid/labels.json" \
  --batch-size 4
)

event efficientdet_lite0 sanity_retry4_started
python "$project/tools/run_effdet_experiment.py" "${inputs[@]}" \
  --sanity \
  --output-directory "$experiment/efficientdet_lite0_sanity_retry4" \
  > "$sanity_log" 2>&1
sanity_exit=$?
event efficientdet_lite0 sanity_retry4_exited "$sanity_exit"
if (( sanity_exit != 0 )); then
  deactivate
  event non_yolo_effdet_retry5 completed "$sanity_exit"
  exit "$sanity_exit"
fi

event efficientdet_lite0 training_retry5_started
python "$project/tools/run_effdet_experiment.py" "${inputs[@]}" \
  --output-directory "$experiment/efficientdet_lite0_screen_seed_20260729_retry2" \
  > "$log" 2>&1
exit_code=$?
event efficientdet_lite0 training_retry5_exited "$exit_code"
deactivate
event non_yolo_effdet_retry5 completed "$exit_code"
exit "$exit_code"
