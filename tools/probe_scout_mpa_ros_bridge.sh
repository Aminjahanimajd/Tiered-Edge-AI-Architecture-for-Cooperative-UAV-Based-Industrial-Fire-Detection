#!/usr/bin/env bash
# Bounded publisher-only probe of the installed ModalAI MPA-to-ROS 2 bridge.

set -euo pipefail

trial_id=${1:?trial id required}
duration_seconds=${2:-15}
image_topic=${3:-/tracking}
root=/home/root/drone_enhanced_evidence/scout_mpa_bridge_probes
trial_root="$root/$trial_id"

case "$duration_seconds" in
  ''|*[!0-9]*) echo "duration must be an integer" >&2; exit 2 ;;
esac
if [ "$duration_seconds" -lt 10 ] || [ "$duration_seconds" -gt 60 ]; then
  echo "duration must be in [10, 60] seconds" >&2
  exit 2
fi
if [ -e "$trial_root" ]; then
  echo "refusing to overwrite $trial_root" >&2
  exit 3
fi
mkdir -p "$trial_root"

set +u
source /opt/ros/foxy/local_setup.bash
source /opt/ros/foxy/mpa_to_ros2/install/setup.bash
set -u

echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "trial_id=$trial_id"
echo "safety_state=propellers_removed; bridge publisher only; no vehicle command"
echo "bridge_executables:"
ros2 pkg executables voxl_mpa_to_ros2

set +e
timeout -s INT "$duration_seconds" \
  ros2 run voxl_mpa_to_ros2 voxl_mpa_to_ros2_node \
  >"$trial_root/bridge_stdout_stderr.log" 2>&1 &
bridge_wrapper_pid=$!
set -e

sleep 6
ros2 node list | sort | tee "$trial_root/nodes.txt"
ros2 topic list -t | sort | tee "$trial_root/topics.txt"

echo "selected_image_topic=$image_topic"
if grep -q "^${image_topic} " "$trial_root/topics.txt"; then
  set +e
  timeout 7 ros2 topic echo "$image_topic" \
    --qos-profile sensor_data --no-arr \
    >"$trial_root/image_topic_samples.txt" 2>&1
  sample_exit=$?
  set -e
else
  sample_exit=4
fi

set +e
wait "$bridge_wrapper_pid"
bridge_exit=$?
set -e

echo "bridge_exit=$bridge_exit"
echo "sample_exit=$sample_exit"
cat "$trial_root/image_topic_samples.txt" 2>/dev/null || true
echo "sample_bytes=$(wc -c < "$trial_root/image_topic_samples.txt" 2>/dev/null || echo 0)"
echo "bridge_log_sha256=$(sha256sum "$trial_root/bridge_stdout_stderr.log" | awk '{print $1}')"
echo "nodes_sha256=$(sha256sum "$trial_root/nodes.txt" | awk '{print $1}')"
echo "topics_sha256=$(sha256sum "$trial_root/topics.txt" | awk '{print $1}')"

if ! grep -q "^${image_topic} " "$trial_root/topics.txt"; then
  echo "status=FAIL_NO_IMAGE_TOPIC"
  exit 4
fi
if [ ! -s "$trial_root/image_topic_samples.txt" ]; then
  echo "status=FAIL_NO_IMAGE_SAMPLES"
  exit 5
fi
if [ "$bridge_exit" -ne 0 ] && [ "$bridge_exit" -ne 124 ] \
  && [ "$bridge_exit" -ne 130 ] && [ "$bridge_exit" -ne 245 ]; then
  echo "status=FAIL_BRIDGE_EXIT"
  exit "$bridge_exit"
fi

echo "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "status=PASS_BOUNDED_BRIDGE_PROBE"
