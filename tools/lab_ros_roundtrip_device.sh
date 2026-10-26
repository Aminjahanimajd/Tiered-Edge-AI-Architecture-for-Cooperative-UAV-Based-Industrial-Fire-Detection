#!/usr/bin/env bash
set -euo pipefail

platform=${1:?platform required}
role=${2:?role required}
trial=${3:?trial required}
count=${4:-100}
current=/tmp/drone_enhanced_lab_2cd839e_r1
experiment=hardware-lab-20260803
prefix="${trial}-event"

common="--experiment-id $experiment --trial-id $trial --event-prefix $prefix --count $count --per-event-timeout-seconds 2 --global-timeout-seconds 180"
echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) platform=$platform role=$role trial=$trial count=$count"

if [ "$platform" = scout ]; then
  set +u
  source /opt/ros/foxy/setup.bash
  source "$current/ros2_ws/install_lab_20260803_r1/setup.bash"
  set -u
  export PYTHONPATH="$current/src:$current/ros2_ws/src/drone_enhanced_nodes:${PYTHONPATH:-}"
  export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  export CYCLONEDDS_URI="file://$current/config/cyclonedds_swarmnet.xml"
  export ROS_DOMAIN_ID=83
  python3 "$current/tools/ros_roundtrip_probe.py" "$role" $common
elif [ "$platform" = sentinel ]; then
  previous=/tmp/drone_enhanced_validation_8b634cd
  docker run --rm --network host \
    -v "$previous:$previous:ro" \
    -v "$current:$current:ro" \
    -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    -e CYCLONEDDS_URI="file://$current/config/cyclonedds_swarmnet.xml" \
    -e ROS_DOMAIN_ID=83 \
    -e PYTHONPATH="$current/src:$current/ros2_ws/src/drone_enhanced_nodes" \
    dustynv/ros:foxy-ros-base-l4t-r32.7.1 \
    bash -lc "source /opt/ros/foxy/install/setup.bash; source $previous/ros2_ws/install_sentinel/setup.bash; python3 $current/tools/ros_roundtrip_probe.py $role $common"
else
  echo "unsupported platform: $platform" >&2
  exit 2
fi

echo "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) status=PASS"
