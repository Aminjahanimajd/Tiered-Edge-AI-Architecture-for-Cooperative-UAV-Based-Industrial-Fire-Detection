#!/usr/bin/env bash
set -u

# [NO LAB] Continuation after an external interruption of the scientifically
# valid retry9 recovery. ckpt-90 is epoch-aligned and retains optimizer state.
project=/mnt/d/Drones/Drone_Enhanced
experiment="$project/artifacts/experiments/model_screening_v1"
events="$experiment/non_yolo_final_retry_events.jsonl"
log="$experiment/queue_logs/efficientdet_lite0_training_retry10_resume_ckpt90.log"
output="$experiment/efficientdet_lite0_screen_seed_20260729_retry10_resume_ckpt90"
checkpoint="$experiment/efficientdet_lite0_screen_seed_20260729_retry9_resume_ckpt50/checkpoints/ckpt-90"

event() {
  printf '{"utc_time":"%s","model_id":"%s","event":"%s","exit_code":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "${3:-null}" >> "$events"
}

if [[ -e "$output" ]]; then
  printf 'Refusing to overwrite existing recovery output: %s\n' "$output" >&2
  exit 2
fi

if [[ ! -f "${checkpoint}.index" || ! -f "${checkpoint}.data-00000-of-00001" ]]; then
  printf 'Incomplete resume checkpoint: %s\n' "$checkpoint" >&2
  exit 3
fi

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

event efficientdet_lite0 training_retry10_resume_ckpt90_started
python "$project/tools/resume_effdet_experiment.py" \
  --train-records "$project/artifacts/training/fire_only_curated_v7_tfrecord_effdet_labels/coco_train.record-*" \
  --train-annotations "$project/artifacts/training/fire_only_curated_v7_coco/train/labels.json" \
  --validation-records "$project/artifacts/training/fire_only_curated_v7_tfrecord_effdet_labels/coco_val.record-*" \
  --validation-annotations "$project/artifacts/training/fire_only_curated_v7_coco/valid/labels.json" \
  --resume-checkpoint "$checkpoint" \
  --output-directory "$output" \
  --batch-size 4 \
  --epochs 100 \
  > "$log" 2>&1
exit_code=$?
event efficientdet_lite0 training_retry10_resume_ckpt90_exited "$exit_code"
deactivate
exit "$exit_code"
