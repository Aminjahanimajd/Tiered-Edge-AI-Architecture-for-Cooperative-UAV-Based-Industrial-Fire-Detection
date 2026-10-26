#!/usr/bin/env bash
# Run one camera-free, non-actuating correlated ROS 2 network probe.

set -euo pipefail

platform=${1:?platform required: scout or sentinel}
role=${2:?role required: initiator or responder}
workspace=${3:?workspace required}
install_tag=${4:?install tag required}
trial_id=${5:?trial id required}
count=${6:-1000}
tool_root=${7:?tool root required}
domain_id=${8:-86}
output=${9:?output file required}
experiment_id=hardware-network-20260925
event_prefix="${trial_id}-event"

if [ -e "$output" ]; then
  echo "refusing to overwrite $output" >&2
  exit 3
fi
mkdir -p "$(dirname "$output")"

common=(
  "$role"
  --experiment-id "$experiment_id"
  --trial-id "$trial_id"
  --event-prefix "$event_prefix"
  --count "$count"
  --per-event-timeout-seconds 2
  --global-timeout-seconds 600
  --publisher-start-delay-seconds 3
)

echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "safety_state=propellers_removed; camera-free message exchange; no vehicle command"
echo "platform=$platform role=$role trial_id=$trial_id count=$count domain_id=$domain_id"

if [ "$platform" = scout ]; then
  set +u
  source /opt/ros/foxy/local_setup.bash
  source "$workspace/ros2_ws/install_$install_tag/setup.bash"
  set -u
  export PYTHONPATH="$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes:${PYTHONPATH:-}"
  export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  export CYCLONEDDS_URI="file://$tool_root/cyclonedds_swarmnet.xml"
  export ROS_DOMAIN_ID="$domain_id"
  python3 "$tool_root/ros_roundtrip_probe.py" "${common[@]}" >"$output"
elif [ "$platform" = sentinel ]; then
  docker run --rm --network host \
    -v "$workspace:$workspace:ro" \
    -v "$tool_root:$tool_root:ro" \
    -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    -e CYCLONEDDS_URI="file://$tool_root/cyclonedds_swarmnet.xml" \
    -e ROS_DOMAIN_ID="$domain_id" \
    -e PYTHONPATH="$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes" \
    dustynv/ros:foxy-ros-base-l4t-r32.7.1 \
    bash -lc "source /opt/ros/foxy/install/setup.bash; source $workspace/ros2_ws/install_$install_tag/setup.bash; python3 $tool_root/ros_roundtrip_probe.py ${common[*]}" \
    >"$output"
else
  echo "unsupported platform: $platform" >&2
  exit 2
fi

sha256sum "$output"
echo "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "status=PASS_ROS2_ROUNDTRIP_ROLE"
