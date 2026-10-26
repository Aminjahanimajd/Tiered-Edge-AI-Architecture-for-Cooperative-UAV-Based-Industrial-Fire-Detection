#!/usr/bin/env bash
set -eu

project=/mnt/d/Drones/Drone_Enhanced
experiment="$project/artifacts/experiments/model_screening_v1"
supervisor_log="$experiment/queue_logs/efficientdet_lite0_supervisor_retry9_resume_ckpt50.log"
pid_record="$experiment/efficientdet_lite0_retry9_resume_ckpt50_launcher.json"

nohup setsid bash "$project/tools/run_effdet_resume_ckpt50.sh" \
  > "$supervisor_log" 2>&1 < /dev/null &
launcher_pid=$!
printf '{"utc_time":"%s","wsl_launcher_pid":%s,"script":"%s"}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$launcher_pid" \
  "$project/tools/run_effdet_resume_ckpt50.sh" > "$pid_record"
printf '%s\n' "$launcher_pid"
