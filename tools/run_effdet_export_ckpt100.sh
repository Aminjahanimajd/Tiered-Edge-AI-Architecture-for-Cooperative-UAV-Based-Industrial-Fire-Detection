#!/usr/bin/env bash
set -eu

# Export does not measure runtime, so force CPU conversion to avoid a WSL GPU
# process termination observed after the corrected retry2 model construction.
# Failed and incomplete export directories are preserved separately.
project=/mnt/d/Drones/Drone_Enhanced
run="$project/artifacts/experiments/model_screening_v1/efficientdet_lite0_screen_seed_20260729_retry10_resume_ckpt90"
log="$run/export_retry3_console.log"
exit_record="$run/export_retry3_exit_code.txt"

source /home/sefroyek/.venvs/drone_enhanced_effdet_py39/bin/activate
export PYTHONPATH="$project/tools"
export CUDA_VISIBLE_DEVICES=-1

set +e
python "$project/tools/export_effdet_checkpoint.py" \
  --checkpoint "$run/checkpoints/ckpt-100" \
  --validation-records "$project/artifacts/training/fire_only_curated_v7_tfrecord_effdet_labels/coco_val.record-*" \
  --validation-annotations "$project/artifacts/training/fire_only_curated_v7_coco/valid/labels.json" \
  --output-directory "$run/export_retry3_cpu" \
  --batch-size 4 \
  --steps-per-epoch 889 \
  > "$log" 2>&1
exit_code=$?
printf '%s\n' "$exit_code" > "$exit_record"
exit "$exit_code"
