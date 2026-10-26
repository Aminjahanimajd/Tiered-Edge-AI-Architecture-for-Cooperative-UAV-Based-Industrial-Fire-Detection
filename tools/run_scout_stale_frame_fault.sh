#!/usr/bin/env bash
# Exercise fail-closed Scout behavior after a live ROS camera stream stops.

set -euo pipefail

trial_id=${1:?trial id required}
duration_seconds=${2:-90}
expected_count=${3:-5}
# Three live alerts generate ten records (first-frame plus three alert/inference/
# verdict triplets), matching the deployed logger's flush_every=10 boundary.
preflight_count=${4:-3}
workspace=/home/root/deployments/drone_enhanced_scout_20260925_r2
install_tag=scout_20260925_r2
experiment_id=hardware-faults-20260928
root=/home/root/drone_enhanced_evidence/faults_20260928/$trial_id
model=/home/root/colcon_ws/best.tflite

case "$duration_seconds" in ''|*[!0-9]*) exit 2;; esac
case "$expected_count" in ''|*[!0-9]*) exit 2;; esac
case "$preflight_count" in ''|*[!0-9]*) exit 2;; esac
if [ "$duration_seconds" -lt 75 ] || [ "$duration_seconds" -gt 180 ]; then
  echo "duration must be in [75, 180] seconds" >&2
  exit 2
fi
if [ "$expected_count" -lt 1 ] || [ "$expected_count" -gt 20 ]; then
  echo "expected count must be in [1, 20]" >&2
  exit 2
fi
if [ "$preflight_count" -lt 1 ] || [ "$preflight_count" -gt 5 ]; then
  echo "preflight count must be in [1, 5]" >&2
  exit 2
fi
if [ -e "$root" ]; then
  echo "refusing to overwrite $root" >&2
  exit 3
fi
if pgrep -af '[v]oxl_mpa_to_ros2_node' >/dev/null; then
  echo "camera bridge is already running; refusing ambiguous setup" >&2
  exit 4
fi

mkdir -p "$root/node_logs"
date -u +%Y-%m-%dT%H:%M:%SZ > "$root/started_utc.txt"
printf '%s\n' \
  "stationary; propellers removed; no flight command; ROS camera bridge intentionally stopped after a verified live frame" \
  > "$root/safety_state.txt"
printf '%s\n' \
  "Scout stale-frame fault at the ROS interface; underlying ModalAI camera service remains running." \
  > "$root/claim_boundary.txt"
printf '%s\n' "$expected_count" > "$root/expected_repetitions.txt"
printf '%s\n' "$preflight_count" > "$root/preflight_repetitions.txt"
voxl-inspect-services > "$root/services_before.txt" 2>&1 || true

set +u
source /opt/ros/foxy/local_setup.bash
source /opt/ros/foxy/mpa_to_ros2/install/setup.bash
source "$workspace/ros2_ws/install_$install_tag/setup.bash"
set -u
export PYTHONPATH="$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes:${PYTHONPATH:-}"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file://$workspace/config/cyclonedds_swarmnet.xml"
export ROS_DOMAIN_ID=85

sha256sum "$model" > "$root/model_sha256.txt"
setsid ros2 run voxl_mpa_to_ros2 voxl_mpa_to_ros2_node \
  > "$root/bridge_stdout_stderr.log" 2>&1 &
bridge_group=$!
node_pid=""
cleanup() {
  kill -TERM -- "-$bridge_group" 2>/dev/null || true
  if [ -n "$node_pid" ]; then kill -INT "$node_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT
sleep 5

set +e
timeout -s INT "$duration_seconds" \
  python3 -m drone_enhanced_nodes.scout_node --ros-args \
    -p formal_mode:=true \
    -p experiment_id:="$experiment_id" \
    -p trial_id:="$trial_id" \
    -p camera_topic:=/tracking \
    -p model_path:="$model" \
    -p interpreter_threads:=1 \
    -p log_directory:="$root/node_logs" \
    -p enable_flight_commands:=false \
  > "$root/node_stdout_stderr.log" 2>&1 &
node_pid=$!
set -e

printf '%s\n' "ready" > "$root/ready_for_live_preflight_probes.txt"
events=""
for unused in $(seq 1 75); do
  events=$(find "$root/node_logs" -name events.jsonl -type f | head -n 1)
  if [ -n "$events" ]; then
    preflight_verdicts=$(grep -F '"event_id":"'"$trial_id"'-preflight-' "$events" \
      | grep -c '"event_type":"hazard_verdict_published"' || true)
    if grep -q '"event_type":"first_camera_frame"' "$events" \
      && [ "$preflight_verdicts" -ge "$preflight_count" ]; then
      break
    fi
  fi
  sleep 1
done
if [ -z "$events" ] || ! grep -q '"event_type":"first_camera_frame"' "$events" \
  || [ "${preflight_verdicts:-0}" -lt "$preflight_count" ]; then
  echo "live-frame preflight was not established before fault injection" >&2
  exit 5
fi
cp "$events" "$root/events_before_bridge_stop.jsonl"
date -u +%Y-%m-%dT%H:%M:%SZ > "$root/first_frame_verified_utc.txt"
printf '%s\n' "$preflight_verdicts" > "$root/preflight_verdict_count.txt"
kill -TERM -- "-$bridge_group" 2>/dev/null || true
sleep 2
date -u +%Y-%m-%dT%H:%M:%SZ > "$root/bridge_stopped_utc.txt"
printf '%s\n' "ready" > "$root/ready_for_fault_probes.txt"

set +e
wait "$node_pid"
node_status=$?
set -e
node_pid=""
printf '%s\n' "$node_status" > "$root/node_exit_code.txt"
manifest=$(find "$root/node_logs" -name session_manifest.json -type f | head -n 1)
events=$(find "$root/node_logs" -name events.jsonl -type f | head -n 1)
if [ -z "$events" ] || [ -z "$manifest" ]; then
  echo "missing node evidence" >&2
  exit 6
fi
cp "$events" "$root/events.jsonl"
cp "$manifest" "$root/session_manifest.json"
alerts=$(grep -c '"event_type":"hazard_alert_received"' "$root/events.jsonl" || true)
preflight_verdicts=$(grep -F '"event_id":"'"$trial_id"'-preflight-' "$root/events.jsonl" \
  | grep -c '"event_type":"hazard_verdict_published"' || true)
stale=$(grep -F '"event_id":"'"$trial_id"'-fault-' "$root/events.jsonl" \
  | grep '"event_type":"hazard_verdict_published"' \
  | grep -c '"reason":"stale_frame"' || true)
printf '%s\n' "$alerts" > "$root/alerts_received_count.txt"
printf '%s\n' "$preflight_verdicts" > "$root/preflight_verdict_count.txt"
printf '%s\n' "$stale" > "$root/stale_frame_verdict_count.txt"
expected_total=$((preflight_count + expected_count))
if [ "$alerts" -ne "$expected_total" ] \
  || [ "$preflight_verdicts" -ne "$preflight_count" ] \
  || [ "$stale" -ne "$expected_count" ]; then
  echo "expected total/preflight/stale $expected_total/$preflight_count/$expected_count; observed $alerts/$preflight_verdicts/$stale" >&2
  exit 7
fi
if [ "$node_status" -ne 0 ] && [ "$node_status" -ne 124 ] && [ "$node_status" -ne 130 ]; then
  echo "unexpected node status: $node_status" >&2
  exit "$node_status"
fi
voxl-inspect-services > "$root/services_after.txt" 2>&1 || true
date -u +%Y-%m-%dT%H:%M:%SZ > "$root/finished_utc.txt"
find "$root" -type f ! -name sha256_manifest.txt -print0 \
  | sort -z | xargs -0 sha256sum > "$root/sha256_manifest.txt"
echo "RESULT_ROOT=$root"
echo "ALERTS=$alerts PREFLIGHT_VERDICTS=$preflight_verdicts STALE_FRAME_VERDICTS=$stale NODE_STATUS=$node_status"
echo "STATUS=PASS_STALE_FRAME_FAULT"
