#!/usr/bin/env bash
set -eo pipefail

platform=${1:?platform required}
output=${2:?output required}
workspace=/tmp/drone_enhanced_lab_2cd839e_r1

if [ "$platform" = scout ]; then
  set +u
  source /opt/ros/foxy/setup.bash
  source /opt/ros/foxy/mpa_to_ros2/install/setup.bash
  source "$workspace/ros2_ws/install_lab_20260803_r1/setup.bash"
  set -u
  export PYTHONPATH="$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes:${PYTHONPATH:-}"
  export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  export ROS_DOMAIN_ID=86
  setsid ros2 run voxl_mpa_to_ros2 voxl_mpa_to_ros2_node >/tmp/diagnostic_bridge.log 2>&1 &
  group=$!
  trap 'kill -TERM -- -$group 2>/dev/null || true; sleep 1; kill -KILL -- -$group 2>/dev/null || true' EXIT
  sleep 4
  python3 "$workspace/tools/capture_diagnostic_frame.py" ros --output "$output"
elif [ "$platform" = sentinel ]; then
  docker run --rm --runtime nvidia --network none --device /dev/video2 \
    -v "$workspace:$workspace" \
    dustynv/ros:foxy-ros-base-l4t-r32.7.1 \
    python3 "$workspace/tools/capture_diagnostic_frame.py" opencv --output "$output"
else
  echo "unsupported platform" >&2
  exit 2
fi
