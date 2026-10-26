#!/usr/bin/env bash
set -euo pipefail

trial=${1:?trial required}
count=${2:-5}
output_dir=${3:?output directory required}
: "${SENTINEL_PASS:?SENTINEL_PASS required}"
: "${SCOUT_PASS:?SCOUT_PASS required}"

workspace=/tmp/drone_enhanced_lab_2cd839e_r1
experiment=hardware-lab-20260803
scout_duration=$((count * 6 + 30))
diagnostic_dir="$workspace/diagnostic/$trial"
mkdir -p "$output_dir/$trial/publishers" "$output_dir/$trial/scout" "$output_dir/$trial/diagnostic_frames"

echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) trial=$trial count=$count condition=unlit propellers=removed flight_commands=false"

SSHPASS="$SCOUT_PASS" sshpass -e ssh -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null root@10.42.0.125 \
  "test ! -e '$diagnostic_dir'; test ! -e '$workspace/lab_sessions/$experiment/$trial'; SCOUT_CONFIDENCE_THRESHOLD=0.05 SCOUT_OUTPUT_COORDINATE_SPACE=normalized SCOUT_DIAGNOSTIC_CAPTURE_DIRECTORY='$diagnostic_dir' bash '$workspace/tools/lab_full_node_device.sh' scout '$trial' '$scout_duration'" \
  >"$output_dir/$trial/scout_node_console.txt" 2>&1 &
scout_pid=$!
sleep 8

for index in $(seq -w 1 "$count"); do
  event_id="${trial}-event-${index}"
  SSHPASS="$SENTINEL_PASS" sshpass -e ssh -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null unime-nano@10.42.0.1 \
    "docker run --rm --network host \
      -v /tmp/drone_enhanced_validation_8b634cd:/tmp/drone_enhanced_validation_8b634cd:ro \
      -v '$workspace':'$workspace':ro \
      -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
      -e CYCLONEDDS_URI=file://$workspace/config/cyclonedds_swarmnet.xml \
      -e ROS_DOMAIN_ID=85 \
      -e PYTHONPATH=$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes \
      dustynv/ros:foxy-ros-base-l4t-r32.7.1 \
      bash -lc 'source /opt/ros/foxy/install/setup.bash; source /tmp/drone_enhanced_validation_8b634cd/ros2_ws/install_sentinel/setup.bash; export PYTHONPATH=$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes:\${PYTHONPATH:-}; python3 $workspace/tools/ros_injected_exchange.py publisher alert --experiment-id $experiment --trial-id $trial --event-id $event_id --source-device sentinel --timeout-seconds 15 --publisher-start-delay-seconds 1'" \
    >"$output_dir/$trial/publishers/${event_id}.json" 2>"$output_dir/$trial/publishers/${event_id}.stderr.txt"
  sleep 2
done

wait "$scout_pid"

SSHPASS="$SCOUT_PASS" sshpass -e scp -q -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  "root@10.42.0.125:$workspace/lab_sessions/$experiment/$trial/scout/"* \
  "$output_dir/$trial/scout/"
SSHPASS="$SCOUT_PASS" sshpass -e scp -q -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  "root@10.42.0.125:$diagnostic_dir/"*.jpg \
  "$output_dir/$trial/diagnostic_frames/"

echo "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) status=PASS_CAPTURE_COMPLETE"
