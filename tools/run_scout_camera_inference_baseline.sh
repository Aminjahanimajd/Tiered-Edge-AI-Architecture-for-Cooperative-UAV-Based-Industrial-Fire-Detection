#!/usr/bin/env bash
set -euo pipefail

trial_id=${1:?trial id required}
duration_seconds=${2:-600}
interpreter_threads=${3:-1}
workspace=/home/root/deployments/drone_enhanced_scout_20260925_r2
evidence_root=/home/root/drone_enhanced_evidence/camera_inference_no_pixhawk_20260928
control_root="$evidence_root/control/$trial_id"

case "$duration_seconds" in ''|*[!0-9]*) exit 2;; esac
if [ "$duration_seconds" -lt 600 ] || [ "$duration_seconds" -gt 1200 ]; then
  echo "duration must be in [600, 1200] seconds" >&2
  exit 2
fi
if [ -e "$control_root" ]; then
  echo "refusing to overwrite $control_root" >&2
  exit 3
fi

mkdir -p "$control_root"
date -u +%Y-%m-%dT%H:%M:%SZ >"$control_root/started_utc.txt"
printf '%s\n' \
  "stationary; propellers removed; Sentinel Pixhawk not required; no command publisher" \
  >"$control_root/safety_state.txt"
printf '%s\n' \
  "Ten-minute live Scout camera plus TFLite verification baseline driven by correlated synthetic alerts; not complete-stack endurance." \
  >"$control_root/claim_boundary.txt"
voxl-inspect-services >"$control_root/services_before.txt" 2>&1 || true

python3 "$workspace/tools/collect_device_resource_series.py" \
  --output-directory "$control_root/resources" \
  --platform scout_voxl2_camera_inference_no_sentinel_pixhawk \
  --interval-seconds 1 \
  --maximum-duration-seconds "$((duration_seconds + 120))" \
  >"$control_root/resource_collector_console.log" 2>&1 &
resource_pid=$!
cleanup() {
  kill -INT "$resource_pid" 2>/dev/null || true
  wait "$resource_pid" 2>/dev/null || true
}
trap cleanup EXIT

set +e
bash "$workspace/tools/run_scout_rebuild_validation.sh" \
  "$workspace" scout_20260925_r2 "$trial_id" "$duration_seconds" \
  /home/root/colcon_ws/best.tflite /tracking \
  camera-inference-no-pixhawk-20260928 "$evidence_root/node_sessions" \
  "$interpreter_threads" \
  >"$control_root/node_runner_console.log" 2>&1
node_status=$?
set -e
cleanup
trap - EXIT

voxl-inspect-services >"$control_root/services_after.txt" 2>&1 || true
date -u +%Y-%m-%dT%H:%M:%SZ >"$control_root/finished_utc.txt"
printf '%s\n' "$node_status" >"$control_root/node_runner_exit_code.txt"
find "$control_root" -type f ! -name sha256_manifest.txt -print0 \
  | sort -z | xargs -0 sha256sum >"$control_root/sha256_manifest.txt"
echo "RESULT_ROOT=$control_root"
echo "NODE_STATUS=$node_status"
exit "$node_status"
