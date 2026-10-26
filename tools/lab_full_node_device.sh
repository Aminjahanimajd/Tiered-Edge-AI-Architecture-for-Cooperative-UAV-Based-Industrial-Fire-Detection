#!/usr/bin/env bash
set -eo pipefail

platform=${1:?platform required}
trial=${2:?trial required}
duration=${3:-30}
scout_confidence_threshold=${SCOUT_CONFIDENCE_THRESHOLD:-0.50}
scout_output_coordinate_space=${SCOUT_OUTPUT_COORDINATE_SPACE:-model_pixels}
scout_diagnostic_capture_directory=${SCOUT_DIAGNOSTIC_CAPTURE_DIRECTORY:-}
workspace=/tmp/drone_enhanced_lab_2cd839e_r1
experiment=hardware-lab-20260803
log_root="$workspace/lab_sessions"
mkdir -p "$log_root"
echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) platform=$platform trial=$trial duration=$duration scout_confidence_threshold=$scout_confidence_threshold scout_output_coordinate_space=$scout_output_coordinate_space scout_diagnostic_capture_directory=$scout_diagnostic_capture_directory"

if [ "$platform" = scout ]; then
  set +u
  source /opt/ros/foxy/setup.bash
  source /opt/ros/foxy/mpa_to_ros2/install/setup.bash
  source "$workspace/ros2_ws/install_lab_20260803_r1/setup.bash"
  set -u
  export PYTHONPATH="$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes:${PYTHONPATH:-}"
  export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  export CYCLONEDDS_URI="file://$workspace/config/cyclonedds_swarmnet.xml"
  export ROS_DOMAIN_ID=85
  setsid ros2 run voxl_mpa_to_ros2 voxl_mpa_to_ros2_node >"$log_root/${trial}_bridge.log" 2>&1 &
  bridge_group=$!
  cleanup() {
    kill -TERM -- "-$bridge_group" 2>/dev/null || true
    sleep 1
    kill -KILL -- "-$bridge_group" 2>/dev/null || true
  }
  trap cleanup EXIT
  sleep 4
  set +e
  timeout -s INT "$duration" python3 -m drone_enhanced_nodes.scout_node --ros-args \
    -p formal_mode:=true -p experiment_id:="$experiment" -p trial_id:="$trial" \
    -p model_path:=/home/root/colcon_ws/best.tflite \
    -p confidence_threshold:="$scout_confidence_threshold" \
    -p output_coordinate_space:="$scout_output_coordinate_space" \
    -p diagnostic_capture_directory:="$scout_diagnostic_capture_directory" \
    -p log_directory:="$log_root" -p enable_flight_commands:=false
  rc=$?
  set -e
elif [ "$platform" = sentinel ]; then
  previous=/tmp/drone_enhanced_validation_8b634cd
  set +e
  docker run --rm --runtime nvidia --network host --device /dev/video2 \
    -v "$previous:$previous:ro" -v "$workspace:$workspace" \
    -v /home/unime-nano/ros2_ws/sentinel_v1.engine:/models/sentinel_v1.engine:ro \
    -v /home/unime-nano/.local/lib/python3.6/site-packages:/host_user_site:ro \
    -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
    -e CYCLONEDDS_URI="file://$workspace/config/cyclonedds_swarmnet.xml" \
    -e ROS_DOMAIN_ID=85 \
    -e PYTHONPATH="$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes" \
    dustynv/ros:foxy-ros-base-l4t-r32.7.1 \
    bash -lc "source /opt/ros/foxy/install/setup.bash; source $previous/ros2_ws/install_sentinel/setup.bash; export PYTHONPATH=$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes:/host_user_site:/usr/local/lib/python3.6/dist-packages:\${PYTHONPATH:-}; timeout -s INT $duration python3 -m drone_enhanced_nodes.sentinel_node --ros-args -p formal_mode:=true -p experiment_id:=$experiment -p trial_id:=$trial -p engine_path:=/models/sentinel_v1.engine -p log_directory:=$log_root -p enable_flight_commands:=false"
  rc=$?
  set -e
else
  echo "unsupported platform: $platform" >&2
  exit 2
fi

echo "node_exit=$rc"
if [ "$rc" -ne 0 ] && [ "$rc" -ne 124 ] && [ "$rc" -ne 130 ]; then
  exit "$rc"
fi
echo "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ) status=PASS_BOUNDED_STOP"
