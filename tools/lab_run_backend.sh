#!/usr/bin/env bash
set -eu

if (( $# != 3 )); then
  echo "usage: SSHPASS=... $0 ROLE USER HOST" >&2
  exit 2
fi

role=$1
remote_user=$2
remote_host=$3
workspace=/tmp/drone_enhanced_lab_2cd839e_r1

ssh_options=(
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

if [ "$role" = sentinel ]; then
  model=/home/unime-nano/ros2_ws/sentinel_v1.engine
  backend=tensorrt
else
  model=/home/root/colcon_ws/best.tflite
  backend=tflite
fi

sshpass -e ssh "${ssh_options[@]}" "$remote_user@$remote_host" bash -s -- \
  "$role" "$workspace" "$backend" "$model" <<'REMOTE'
set -eu
role=$1
workspace=$2
backend=$3
model=$4
export PYTHONPATH="$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes${PYTHONPATH:+:$PYTHONPATH}"
if [ "$role" = sentinel ]; then
  extra=()
else
  extra=(--threads 4)
fi
printf 'run_utc='; date -u +%Y-%m-%dT%H:%M:%SZ
printf 'role=%s\n' "$role"
printf 'hostname='; hostname
printf 'model='; sha256sum "$model"
printf 'source_validate='; sha256sum "$workspace/tools/validate_device_backend.py"
printf 'source_benchmark='; sha256sum "$workspace/tools/benchmark_device_backend.py"
python3 -m py_compile \
  "$workspace/tools/validate_device_backend.py" \
  "$workspace/tools/benchmark_device_backend.py"
printf '%s\n' '--- validation ---'
python3 "$workspace/tools/validate_device_backend.py" "$backend" "$model" "${extra[@]}"
printf '%s\n' '--- benchmark ---'
python3 "$workspace/tools/benchmark_device_backend.py" "$backend" "$model" \
  "${extra[@]}" --warmup 10 --iterations 100 --resize-mode letterbox
printf 'completed_utc='; date -u +%Y-%m-%dT%H:%M:%SZ
REMOTE
