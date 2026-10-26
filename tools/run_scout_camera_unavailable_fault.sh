#!/usr/bin/env bash
# Exercise fail-closed Scout behavior with the ROS camera bridge absent.

set -euo pipefail

trial_id=${1:?trial id required}
duration_seconds=${2:-75}
expected_count=${3:-5}
workspace=/home/root/deployments/drone_enhanced_scout_20260925_r2
install_tag=scout_20260925_r2
experiment_id=hardware-faults-20260928
root=/home/root/drone_enhanced_evidence/faults_20260928/$trial_id
model=/home/root/colcon_ws/best.tflite

case "$duration_seconds" in ''|*[!0-9]*) exit 2;; esac
case "$expected_count" in ''|*[!0-9]*) exit 2;; esac
if [ "$duration_seconds" -lt 60 ] || [ "$duration_seconds" -gt 180 ]; then
  echo "duration must be in [60, 180] seconds" >&2
  exit 2
fi
if [ "$expected_count" -lt 1 ] || [ "$expected_count" -gt 20 ]; then
  echo "expected count must be in [1, 20]" >&2
  exit 2
fi
if [ -e "$root" ]; then
  echo "refusing to overwrite $root" >&2
  exit 3
fi
if pgrep -af '[v]oxl_mpa_to_ros2_node' >/dev/null; then
  echo "camera bridge is already running; refusing ambiguous fault setup" >&2
  exit 4
fi

mkdir -p "$root/node_logs"
date -u +%Y-%m-%dT%H:%M:%SZ > "$root/started_utc.txt"
printf '%s\n' \
  "stationary; propellers removed; no flight command; ROS camera bridge intentionally absent" \
  > "$root/safety_state.txt"
printf '%s\n' \
  "Scout ROS camera-interface-unavailable fault; underlying camera service is not stopped." \
  > "$root/claim_boundary.txt"
printf '%s\n' "$expected_count" > "$root/expected_repetitions.txt"
voxl-inspect-services > "$root/services_before.txt" 2>&1 || true

set +u
source /opt/ros/foxy/local_setup.bash
source "$workspace/ros2_ws/install_$install_tag/setup.bash"
set -u
export PYTHONPATH="$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes:${PYTHONPATH:-}"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file://$workspace/config/cyclonedds_swarmnet.xml"
export ROS_DOMAIN_ID=85

ros2 topic list -t | sort > "$root/topics_before.txt"
ros2 topic info /tracking > "$root/tracking_topic_before.txt" 2>&1 || true
sha256sum "$model" > "$root/model_sha256.txt"

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
  > "$root/node_stdout_stderr.log" 2>&1
node_status=$?
set -e

printf '%s\n' "$node_status" > "$root/node_exit_code.txt"
events=$(find "$root/node_logs" -name events.jsonl -type f | head -n 1)
manifest=$(find "$root/node_logs" -name session_manifest.json -type f | head -n 1)
if [ -z "$events" ] || [ -z "$manifest" ]; then
  echo "missing node evidence" >&2
  exit 5
fi
cp "$events" "$root/events.jsonl"
cp "$manifest" "$root/session_manifest.json"

alerts=$(grep -c '"event_type":"hazard_alert_received"' "$root/events.jsonl" || true)
no_frame=$(grep -c '"event_type":"hazard_verdict_published".*"reason":"no_frame"' "$root/events.jsonl" || true)
printf '%s\n' "$alerts" > "$root/alerts_received_count.txt"
printf '%s\n' "$no_frame" > "$root/no_frame_verdict_count.txt"
if [ "$alerts" -ne "$expected_count" ] || [ "$no_frame" -ne "$expected_count" ]; then
  echo "expected $expected_count alerts/no-frame verdicts; observed $alerts/$no_frame" >&2
  exit 6
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
echo "ALERTS=$alerts NO_FRAME_VERDICTS=$no_frame NODE_STATUS=$node_status"
echo "STATUS=PASS_CAMERA_INTERFACE_UNAVAILABLE_FAULT"
