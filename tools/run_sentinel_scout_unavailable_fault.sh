#!/usr/bin/env bash
# Run the exact Sentinel node's timeout path while the Scout verifier is absent.

set -euo pipefail

trial_id=${1:?trial id required}
repetitions=${2:-5}
workspace=/home/unime-nano/deployments/drone_enhanced_2a0b4dd_20260924
build_tag=sentinel_rebuild_20260925_r3b
tool_root="$workspace/fault_tools_20260928"
model=/home/unime-nano/ros2_ws/sentinel_v1.engine
python_site=/home/unime-nano/restored_python_site_20260924/site-packages
camera_device=/dev/video2
image=dustynv/ros:foxy-ros-base-l4t-r32.7.1
root=/home/unime-nano/hardware_evidence_20260928/faults_20260928/$trial_id
session_root="$root/node_logs"
expected_model_sha256=16f9018ac299c6f525610a877d798392ec26d53fccb84b589ff6533d76589bf2

case "$repetitions" in ''|*[!0-9]*) exit 2;; esac
if [ "$repetitions" -lt 1 ] || [ "$repetitions" -gt 20 ]; then
  echo "repetitions must be in [1, 20]" >&2
  exit 2
fi
if [ -e "$root" ]; then
  echo "refusing to overwrite $root" >&2
  exit 3
fi
if systemctl is-active --quiet camera-stream.service; then
  echo "camera-stream.service must be inactive" >&2
  exit 4
fi
actual_model_sha256=$(sha256sum "$model" | awk '{print $1}')
if [ "$actual_model_sha256" != "$expected_model_sha256" ]; then
  echo "unexpected Sentinel engine hash: $actual_model_sha256" >&2
  exit 5
fi

mkdir -p "$root" "$session_root"
date -u +%Y-%m-%dT%H:%M:%SZ > "$root/started_utc.txt"
printf '%s\n' \
  "stationary; propellers removed; Pixhawk unpowered; no flight command; Scout verifier absent" \
  > "$root/safety_state.txt"
printf '%s\n' \
  "Synthetic detections enter the deployed Sentinel dispatch boundary; camera detection is outside this fault test." \
  > "$root/claim_boundary.txt"
printf '%s\n' "$repetitions" > "$root/expected_repetitions.txt"
sha256sum "$model" > "$root/model_sha256.txt"
sha256sum "$tool_root/run_sentinel_scout_unavailable_fault.py" > "$root/harness_sha256.txt"

set +e
docker run --rm \
  --runtime nvidia \
  --network host \
  --device "$camera_device" \
  -v "$workspace:$workspace:ro" \
  -v "$model:/models/sentinel_v1.engine:ro" \
  -v "$python_site:/host_user_site:ro" \
  -v "$root:$root:rw" \
  -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
  -e CYCLONEDDS_URI="file://$workspace/config/cyclonedds_swarmnet.xml" \
  -e ROS_DOMAIN_ID=85 \
  -e PYTHONPATH="$workspace/src:$workspace/ros2_ws/src/drone_enhanced_nodes:/host_user_site" \
  "$image" \
  bash -lc "source /opt/ros/foxy/install/setup.bash; source $workspace/ros2_ws/install_$build_tag/setup.bash; python3 $tool_root/run_sentinel_scout_unavailable_fault.py --count $repetitions --output $root/probe_summary.json --ros-args -p formal_mode:=true -p experiment_id:=hardware-faults-20260928 -p trial_id:=$trial_id -p camera_device:=$camera_device -p engine_path:=/models/sentinel_v1.engine -p log_directory:=$session_root -p enable_flight_commands:=false" \
  > "$root/node_stdout_stderr.log" 2>&1
status=$?
set -e
printf '%s\n' "$status" > "$root/node_exit_code.txt"
if [ "$status" -ne 0 ]; then
  echo "Sentinel unavailable-Scout harness failed: $status" >&2
  exit "$status"
fi
test -s "$root/probe_summary.json"
grep -q '"status": "PASS"' "$root/probe_summary.json"
date -u +%Y-%m-%dT%H:%M:%SZ > "$root/finished_utc.txt"
find "$root" -type f ! -name sha256_manifest.txt -print0 \
  | sort -z | xargs -0 sha256sum > "$root/sha256_manifest.txt"
echo "RESULT_ROOT=$root"
echo "STATUS=PASS_SCOUT_PROCESS_UNAVAILABLE"
