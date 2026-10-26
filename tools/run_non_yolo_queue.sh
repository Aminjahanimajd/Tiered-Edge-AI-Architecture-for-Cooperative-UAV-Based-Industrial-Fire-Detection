#!/usr/bin/env bash
set -u

project=/mnt/d/Drones/Drone_Enhanced
experiment="$project/artifacts/experiments/model_screening_v1"
events="$experiment/non_yolo_wsl_queue_events.jsonl"
logs="$experiment/queue_logs"
mkdir -p "$logs"

event() {
  printf '{"utc_time":"%s","model_id":"%s","event":"%s","exit_code":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "${3:-null}" >> "$events"
}

wait_for_file() {
  while [[ ! -f "$1" ]]; do sleep 20; done
}

wait_for_cool_gpu() {
  while true; do
    temperature="$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits | head -1 | tr -d ' ')"
    [[ "$temperature" =~ ^[0-9]+$ ]] && (( temperature < 65 )) && return
    sleep 20
  done
}

event non_yolo_queue waiting_for_remaining_yolo
wait_for_file "$experiment/yolov8n_640_screen_seed_20260729_resume1_evidence/run_summary.json"
wait_for_file "$experiment/yolov8s_416_screen_seed_20260729_evidence/run_summary.json"
wait_for_cool_gpu
event non_yolo_queue remaining_yolo_finished

source /home/sefroyek/.venvs/drone_enhanced_tf_py311/bin/activate
export PYTHONPATH=/home/sefroyek/.local/share/drone_enhanced/tensorflow_models_r2.15.0/research:/home/sefroyek/.local/share/drone_enhanced/tensorflow_models_r2.15.0/research/slim
ssd_config="$project/config/ssd_mobilenet_v2_fpnlite_320_screen_batch8_v1.config"
ssd_runner="$project/tools/run_ssd_model_main.py"

event ssd_mobilenet_v2 sanity_started
python "$ssd_runner" --pipeline_config_path="$ssd_config" \
  --model_dir="$experiment/ssd_mobilenet_v2_sanity_retry4" \
  --num_train_steps=1 --alsologtostderr > "$logs/ssd_mobilenet_v2_sanity_wsl.log" 2>&1
ssd_gate=$?
event ssd_mobilenet_v2 sanity_exited "$ssd_gate"
deactivate
wait_for_cool_gpu

source /home/sefroyek/.venvs/drone_enhanced_effdet_py39/bin/activate
export PYTHONPATH="$project/tools"
export TFHUB_CACHE_DIR="$project/artifacts/models/tfhub_cache"
nvidia_libs="$(find /home/sefroyek/.venvs/drone_enhanced_effdet_py39/lib/python3.9/site-packages/nvidia -type d -name lib | paste -sd:)"
export LD_LIBRARY_PATH="$nvidia_libs:${LD_LIBRARY_PATH:-}"
effdet_runner="$project/tools/run_effdet_experiment.py"
effdet_inputs=(
  --train-records "$project/artifacts/training/fire_only_curated_v7_tfrecord/coco_train.record-*"
  --train-annotations "$project/artifacts/training/fire_only_curated_v7_coco/train/labels.json"
  --validation-records "$project/artifacts/training/fire_only_curated_v7_tfrecord/coco_val.record-*"
  --validation-annotations "$project/artifacts/training/fire_only_curated_v7_coco/valid/labels.json"
  --batch-size 4
)

event efficientdet_lite0 sanity_started
python "$effdet_runner" "${effdet_inputs[@]}" \
  --output-directory "$experiment/efficientdet_lite0_sanity" --sanity \
  > "$logs/efficientdet_lite0_sanity_wsl.log" 2>&1
effdet_gate=$?
event efficientdet_lite0 sanity_exited "$effdet_gate"
deactivate
wait_for_cool_gpu

if (( ssd_gate == 0 )); then
  source /home/sefroyek/.venvs/drone_enhanced_tf_py311/bin/activate
  export PYTHONPATH=/home/sefroyek/.local/share/drone_enhanced/tensorflow_models_r2.15.0/research:/home/sefroyek/.local/share/drone_enhanced/tensorflow_models_r2.15.0/research/slim
  event ssd_mobilenet_v2 training_started
  python "$ssd_runner" --pipeline_config_path="$ssd_config" \
    --model_dir="$experiment/ssd_mobilenet_v2_screen_seed_20260729" \
    --num_train_steps=44500 --alsologtostderr > "$logs/ssd_mobilenet_v2_training_wsl.log" 2>&1
  event ssd_mobilenet_v2 training_exited "$?"
  deactivate
else
  event ssd_mobilenet_v2 training_not_admitted "$ssd_gate"
fi
wait_for_cool_gpu

if (( effdet_gate == 0 )); then
  source /home/sefroyek/.venvs/drone_enhanced_effdet_py39/bin/activate
  export PYTHONPATH="$project/tools"
  export TFHUB_CACHE_DIR="$project/artifacts/models/tfhub_cache"
  export LD_LIBRARY_PATH="$nvidia_libs:${LD_LIBRARY_PATH:-}"
  event efficientdet_lite0 training_started
  python "$effdet_runner" "${effdet_inputs[@]}" \
    --output-directory "$experiment/efficientdet_lite0_screen_seed_20260729" \
    > "$logs/efficientdet_lite0_training_wsl.log" 2>&1
  event efficientdet_lite0 training_exited "$?"
  deactivate
else
  event efficientdet_lite0 training_not_admitted "$effdet_gate"
fi

event non_yolo_queue completed
