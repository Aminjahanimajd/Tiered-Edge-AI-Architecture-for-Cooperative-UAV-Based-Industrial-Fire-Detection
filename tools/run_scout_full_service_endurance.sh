#!/usr/bin/env bash
set -euo pipefail

trial_id=${1:?trial id required}
duration_seconds=${2:-1800}
workspace=/home/root/deployments/drone_enhanced_scout_20260925_r2
evidence_root=${SCOUT_EVIDENCE_ROOT:-/home/root/drone_enhanced_evidence/full_service_20260929}
control_root="$evidence_root/control/$trial_id"
interpreter_threads=${SCOUT_INTERPRETER_THREADS:-1}
experiment_id=${FULL_SERVICE_EXPERIMENT_ID:-full-service-20260929}

case "$duration_seconds" in ''|*[!0-9]*) exit 2;; esac
if [ "$duration_seconds" -lt 600 ] || [ "$duration_seconds" -gt 3600 ]; then
  echo "duration must be in [600, 3600] seconds" >&2; exit 2
fi
case "$interpreter_threads" in
  1|2|3|4) ;;
  *) echo "SCOUT_INTERPRETER_THREADS must be in [1, 4]" >&2; exit 2 ;;
esac
if [ -e "$control_root" ]; then echo "refusing to overwrite $control_root" >&2; exit 3; fi
mkdir -p "$control_root"
date -u +%Y-%m-%dT%H:%M:%SZ >"$control_root/started_utc.txt"
printf '%s\n' "stationary; propellers removed; enable_flight_commands=false; no command publisher" >"$control_root/safety_state.txt"
printf '%s\n' "$interpreter_threads" >"$control_root/interpreter_threads.txt"
printf '%s\n' "$experiment_id" >"$control_root/experiment_id.txt"
voxl-inspect-services >"$control_root/services_before.txt" 2>&1 || true

python3 "$workspace/tools/collect_device_resource_series.py" \
  --output-directory "$control_root/resources" \
  --platform scout_voxl2_full_service \
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
  "$experiment_id" "$evidence_root/node_sessions" \
  "$interpreter_threads" \
  >"$control_root/node_runner_console.log" 2>&1
node_status=$?
set -e
cleanup
trap - EXIT
voxl-inspect-services >"$control_root/services_after.txt" 2>&1 || true
date -u +%Y-%m-%dT%H:%M:%SZ >"$control_root/finished_utc.txt"
printf '%s\n' "$node_status" >"$control_root/node_runner_exit_code.txt"
find "$control_root" -type f ! -name sha256_manifest.txt -print0 | sort -z | xargs -0 sha256sum >"$control_root/sha256_manifest.txt"
echo "RESULT_ROOT=$control_root"
echo "NODE_STATUS=$node_status"
exit "$node_status"
