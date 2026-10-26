#!/usr/bin/env bash
# Capture a bounded receive-only Pixhawk snapshot and restore MAVProxy.

set -euo pipefail

trial_id=${1:?trial id required}
duration_seconds=${2:-60}
workspace=/home/unime-nano/deployments/drone_enhanced_2a0b4dd_20260924
tool_root="$workspace/fault_tools_20260928"
root=/home/unime-nano/hardware_evidence_20260928/pixhawk_readonly/$trial_id
device=/dev/ttyTHS1

case "$duration_seconds" in ''|*[!0-9]*) exit 2;; esac
if [ "$duration_seconds" -lt 20 ] || [ "$duration_seconds" -gt 180 ]; then exit 2; fi
if [ -e "$root" ]; then echo "refusing to overwrite $root" >&2; exit 3; fi
test -c "$device"
mkdir -p "$root"
date -u +%Y-%m-%dT%H:%M:%SZ > "$root/started_utc.txt"
printf '%s\n' "propellers removed; receive-only MAVLink; no send, arm, motor, mode, mission, or parameter request" > "$root/safety_state.txt"
systemctl --no-pager --full status mavproxy.service > "$root/mavproxy_before.txt" 2>&1 || true
journalctl -u mavproxy.service -n 40 --no-pager > "$root/mavproxy_journal_before.txt" 2>&1 || true
ls -l "$device" > "$root/serial_device.txt"
lsof "$device" > "$root/serial_owners_before.txt" 2>&1 || true

restore_service() {
  systemctl start mavproxy.service || true
}
trap restore_service EXIT
systemctl stop mavproxy.service
sleep 2
lsof "$device" > "$root/serial_owners_during_probe.txt" 2>&1 || true
set +e
PYTHONPATH=/home/unime-nano/mavproxy_runtime_20260924/site-packages \
  python3 "$tool_root/probe_pixhawk_mavlink_readonly.py" --device "$device" --baud 57600 --duration-seconds "$duration_seconds" > "$root/telemetry.json" 2> "$root/probe_stderr.txt"
probe_status=$?
set -e
printf '%s\n' "$probe_status" > "$root/probe_exit_code.txt"
restore_service
trap - EXIT
sleep 5
systemctl --no-pager --full status mavproxy.service > "$root/mavproxy_after.txt" 2>&1 || true
journalctl -u mavproxy.service -n 60 --no-pager > "$root/mavproxy_journal_after.txt" 2>&1 || true
lsof "$device" > "$root/serial_owners_after.txt" 2>&1 || true
sha256sum "$workspace/ros2_ws/src/drone_enhanced_nodes/drone_enhanced_nodes/sentinel_node.py" > "$root/sentinel_node_sha256.txt"
grep -nE 'enable_flight_commands|flight commands are intentionally unavailable' "$workspace/ros2_ws/src/drone_enhanced_nodes/drone_enhanced_nodes/sentinel_node.py" > "$root/stationary_node_safety_gate.txt"
if [ "$probe_status" -ne 0 ]; then echo "receive-only probe failed" >&2; exit "$probe_status"; fi
grep -q '"status": "PASS"' "$root/telemetry.json"
systemctl is-active --quiet mavproxy.service
date -u +%Y-%m-%dT%H:%M:%SZ > "$root/finished_utc.txt"
find "$root" -type f ! -name sha256_manifest.txt -print0 | sort -z | xargs -0 sha256sum > "$root/sha256_manifest.txt"
echo "RESULT_ROOT=$root"
echo "STATUS=PASS_RECEIVE_ONLY_PIXHAWK_SNAPSHOT"
