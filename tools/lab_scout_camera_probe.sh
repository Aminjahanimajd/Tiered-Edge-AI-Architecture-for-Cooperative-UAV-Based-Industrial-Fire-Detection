#!/usr/bin/env bash
set -eo pipefail

workspace=${1:-/tmp/drone_enhanced_lab_2cd839e_r1}
bridge_log=${2:-/tmp/scout_camera_bridge_20260803.log}
set +u
source /opt/ros/foxy/setup.bash
source /opt/ros/foxy/mpa_to_ros2/install/setup.bash
source "$workspace/ros2_ws/install_lab_20260803_r1/setup.bash"
set -u
export PYTHONPATH="$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes:${PYTHONPATH:-}"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=84

echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "camera_service=$(systemctl is-active voxl-camera-server || true)"
setsid ros2 run voxl_mpa_to_ros2 voxl_mpa_to_ros2_node >"$bridge_log" 2>&1 &
bridge_group=$!
cleanup() {
  kill -TERM -- "-$bridge_group" 2>/dev/null || true
  sleep 1
  kill -KILL -- "-$bridge_group" 2>/dev/null || true
}
trap cleanup EXIT
sleep 4

echo "--- metadata ---"
python3 "$workspace/tools/probe_ros_image_metadata.py" \
  --topic /hires_small_color --sample-count 30 --timeout-seconds 20
echo "--- decode ---"
python3 "$workspace/tools/probe_ros_image_decode.py" \
  --topic /hires_small_color --sample-count 10 --timeout-seconds 20
echo "--- bridge tail ---"
tail -n 40 "$bridge_log" || true
echo "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) status=PASS"
