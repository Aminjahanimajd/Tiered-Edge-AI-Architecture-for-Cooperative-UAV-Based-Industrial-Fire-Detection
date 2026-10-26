#!/usr/bin/env bash
# Run the non-actuating live-Scout hierarchy probe from the Sentinel host.

set -euo pipefail

workspace=${1:?workspace required}
install_tag=${2:?install tag required}
tool_root=${3:?tool root required}
experiment_id=${4:?experiment id required}
trial_id=${5:?trial id required}
event_id=${6:?event id required}
domain_id=${7:-85}
output=${8:?output file required}

if [ -e "$output" ]; then
  echo "refusing to overwrite $output" >&2
  exit 3
fi
mkdir -p "$(dirname "$output")"
echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "safety_state=propellers_removed; injected alert only; no vehicle command"
docker run --rm --network host \
  -v "$workspace:$workspace:ro" \
  -v "$tool_root:$tool_root:ro" \
  -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
  -e CYCLONEDDS_URI="file://$tool_root/cyclonedds_swarmnet.xml" \
  -e ROS_DOMAIN_ID="$domain_id" \
  -e PYTHONPATH="$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes" \
  dustynv/ros:foxy-ros-base-l4t-r32.7.1 \
  bash -lc "source /opt/ros/foxy/install/setup.bash; source $workspace/ros2_ws/install_$install_tag/setup.bash; python3 $tool_root/ros_hierarchy_probe.py --experiment-id $experiment_id --trial-id $trial_id --event-id $event_id --timeout-seconds 45" \
  >"$output"
sha256sum "$output"
echo "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "status=PASS_LIVE_SCOUT_HIERARCHY_PROBE"
