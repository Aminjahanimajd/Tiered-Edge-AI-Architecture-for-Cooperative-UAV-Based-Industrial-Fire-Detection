#!/usr/bin/env bash
# Capture one read-only Scout camera frame through the installed MPA/ROS bridge.

set -euo pipefail

trial_id=${1:?trial id required}
image_topic=${2:-/tracking}
root=/home/root/drone_enhanced_evidence/scout_visual_captures
trial_root="$root/$trial_id"

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
echo "safety_state=propellers_removed; publisher/subscriber only; no vehicle command"
echo "selected_image_topic=$image_topic"

setsid ros2 run voxl_mpa_to_ros2 voxl_mpa_to_ros2_node \
  >"$trial_root/bridge_stdout_stderr.log" 2>&1 &
bridge_group=$!
cleanup() {
  kill -TERM -- "-$bridge_group" 2>/dev/null || true
  sleep 1
  kill -KILL -- "-$bridge_group" 2>/dev/null || true
}
trap cleanup EXIT
sleep 6

python3 /home/root/capture_ros_image_evidence.py \
  --topic "$image_topic" \
  --output "$trial_root/scout_tracking_frame.png" \
  --metadata-output "$trial_root/scout_tracking_frame.json" \
  --timeout-seconds 20 \
  | tee "$trial_root/capture_stdout.log"

ros2 node list | sort >"$trial_root/nodes.txt"
ros2 topic list -t | sort >"$trial_root/topics.txt"
sha256sum "$trial_root"/* | sort >"$trial_root/sha256_manifest.txt"
echo "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "status=PASS_VISUAL_EVIDENCE_CAPTURE"
