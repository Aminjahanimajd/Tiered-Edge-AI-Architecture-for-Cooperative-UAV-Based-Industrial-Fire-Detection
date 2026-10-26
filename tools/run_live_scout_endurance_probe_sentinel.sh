#!/usr/bin/env bash
set -euo pipefail

trial_id=${1:?trial id required}
duration_seconds=${2:-1800}
workspace=/home/unime-nano/deployments/drone_enhanced_2a0b4dd_20260924
full_service_root=${SENTINEL_EVIDENCE_ROOT:-/home/unime-nano/hardware_evidence_20260929/full_service}
evidence_root="$full_service_root/hierarchy_probe"
output="$evidence_root/$trial_id"
experiment_id=${FULL_SERVICE_EXPERIMENT_ID:-full-service-20260929}
image=${SENTINEL_ROS_IMAGE:-dustynv/ros:foxy-ros-base-l4t-r32.7.1}
if [ -e "$output" ]; then echo "refusing to overwrite $output" >&2; exit 3; fi
mkdir -p "$evidence_root"

docker run --rm --network host \
  -v "$workspace:$workspace:ro" \
  -v "$evidence_root:$evidence_root:rw" \
  -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
  -e CYCLONEDDS_URI="file://$workspace/config/cyclonedds_swarmnet.xml" \
  -e ROS_DOMAIN_ID=85 \
  -e PYTHONPATH="$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes" \
  "$image" bash -lc \
  "source /opt/ros/foxy/install/setup.bash; source $workspace/ros2_ws/install_sentinel_rebuild_20260925_r3b/setup.bash; python3 $workspace/tools/ros_live_scout_endurance_probe.py --experiment-id $experiment_id --trial-id $trial_id --output-directory $output --duration-seconds $duration_seconds --interval-seconds 5 --verdict-timeout-seconds 3"
