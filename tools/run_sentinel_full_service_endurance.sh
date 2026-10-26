#!/usr/bin/env bash
set -euo pipefail

trial_id=${1:?trial id required}
duration_seconds=${2:-1800}
workspace=/home/unime-nano/deployments/drone_enhanced_2a0b4dd_20260924
build_tag=sentinel_rebuild_20260925_r3b
evidence_root=${SENTINEL_EVIDENCE_ROOT:-/home/unime-nano/hardware_evidence_20260929/full_service}
control_root="$evidence_root/control/$trial_id"

case "$duration_seconds" in ''|*[!0-9]*) exit 2;; esac
if [ "$duration_seconds" -lt 600 ] || [ "$duration_seconds" -gt 3600 ]; then
  echo "duration must be in [600, 3600] seconds" >&2; exit 2
fi
if [ -e "$control_root" ]; then echo "refusing to overwrite $control_root" >&2; exit 3; fi
mkdir -p "$control_root"
if systemctl is-active --quiet camera-stream.service; then
  echo "camera-stream.service must be inactive" >&2; exit 4
fi
systemctl status mavproxy.service --no-pager >"$control_root/mavproxy_before.txt" 2>&1 || true
date -u +%Y-%m-%dT%H:%M:%SZ >"$control_root/started_utc.txt"
printf '%s\n' "stationary; propellers removed; enable_flight_commands=false" >"$control_root/safety_state.txt"

python3 "$workspace/tools/collect_device_resource_series.py" \
  --output-directory "$control_root/resources" \
  --platform sentinel_jetson_nano_full_service \
  --interval-seconds 1 \
  --maximum-duration-seconds "$((duration_seconds + 120))" \
  >"$control_root/resource_collector_console.log" 2>&1 &
resource_pid=$!
tegrastats --interval 1000 >"$control_root/tegrastats.log" 2>&1 &
tegra_pid=$!
cleanup() {
  kill -INT "$resource_pid" 2>/dev/null || true
  kill -TERM "$tegra_pid" 2>/dev/null || true
  wait "$resource_pid" 2>/dev/null || true
  wait "$tegra_pid" 2>/dev/null || true
}
trap cleanup EXIT

set +e
bash "$workspace/tools/run_sentinel_rebuild_validation.sh" \
  "$workspace" "$build_tag" "$trial_id" "$duration_seconds" \
  /home/unime-nano/ros2_ws/sentinel_v1.engine \
  /home/unime-nano/restored_python_site_20260924/site-packages \
  /dev/video2 "$evidence_root" \
  >"$control_root/node_runner_console.log" 2>&1
node_status=$?
set -e
cleanup
trap - EXIT
systemctl status mavproxy.service --no-pager >"$control_root/mavproxy_after.txt" 2>&1 || true
date -u +%Y-%m-%dT%H:%M:%SZ >"$control_root/finished_utc.txt"
printf '%s\n' "$node_status" >"$control_root/node_runner_exit_code.txt"
find "$control_root" -type f ! -name sha256_manifest.txt -print0 | sort -z | xargs -0 sha256sum >"$control_root/sha256_manifest.txt"
echo "RESULT_ROOT=$control_root"
echo "NODE_STATUS=$node_status"
exit "$node_status"
