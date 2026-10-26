#!/usr/bin/env bash
set -euo pipefail

role=${1:?role required: sentinel or scout}
workspace=${2:-/tmp/drone_enhanced_lab_2cd839e_r1}
tag=${3:-lab_20260803}

echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "role=$role"
echo "workspace=$workspace"
echo "tag=$tag"
test -f "$workspace/ros2_ws/src/drone_enhanced_interfaces/package.xml"
test -f "$workspace/ros2_ws/src/drone_enhanced_nodes/package.xml"

if [ "$role" = scout ]; then
  set +u
  source /opt/ros/foxy/setup.bash
  set -u
  cd "$workspace/ros2_ws"
  export PYTHONPATH="$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes:${PYTHONPATH:-}"
  colcon --log-base "log_$tag" build \
    --build-base "build_$tag" \
    --install-base "install_$tag" \
    --symlink-install
  set +u
  source "$workspace/ros2_ws/install_$tag/setup.bash"
  set -u
  python3 "$workspace/tools/check_ros_imports.py" scout
elif [ "$role" = sentinel ]; then
  docker run --rm --network none \
    -v "$workspace:$workspace" \
    -w "$workspace/ros2_ws" \
    dustynv/ros:foxy-ros-base-l4t-r32.7.1 \
    bash -lc "source /opt/ros/foxy/install/setup.bash && export PYTHONPATH=$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes:\${PYTHONPATH:-} && colcon --log-base log_$tag build --build-base build_$tag --install-base install_$tag --symlink-install --executor sequential && source install_$tag/setup.bash && python3 $workspace/tools/check_ros_imports.py sentinel"
else
  echo "unsupported role: $role" >&2
  exit 2
fi

echo "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "status=PASS"
