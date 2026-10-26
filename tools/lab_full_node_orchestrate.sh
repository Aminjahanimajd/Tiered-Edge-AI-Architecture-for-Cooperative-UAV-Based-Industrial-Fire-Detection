#!/usr/bin/env bash
set -euo pipefail

trial=${1:?trial required}
duration=${2:-30}
output_dir=${3:?output directory required}
mkdir -p "$output_dir"
: "${SENTINEL_PASS:?SENTINEL_PASS required}"
: "${SCOUT_PASS:?SCOUT_PASS required}"
scout_confidence_threshold=${SCOUT_CONFIDENCE_THRESHOLD:-0.50}
scout_output_coordinate_space=${SCOUT_OUTPUT_COORDINATE_SPACE:-model_pixels}
scout_diagnostic_capture_directory=${SCOUT_DIAGNOSTIC_CAPTURE_DIRECTORY:-}

restore_stream() {
  SSHPASS="$SENTINEL_PASS" sshpass -e ssh -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null unime-nano@10.42.0.1 \
    "printf '%s\\n' '$SENTINEL_PASS' | sudo -S systemctl start camera-stream.service; systemctl is-active camera-stream.service" \
    >"$output_dir/${trial}_sentinel_stream_restore.txt" 2>&1 || true
}
trap restore_stream EXIT

SSHPASS="$SCOUT_PASS" sshpass -e ssh -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null root@10.42.0.125 \
  "SCOUT_CONFIDENCE_THRESHOLD='$scout_confidence_threshold' SCOUT_OUTPUT_COORDINATE_SPACE='$scout_output_coordinate_space' SCOUT_DIAGNOSTIC_CAPTURE_DIRECTORY='$scout_diagnostic_capture_directory' bash /tmp/drone_enhanced_lab_2cd839e_r1/tools/lab_full_node_device.sh scout $trial $((duration + 10))" \
  >"$output_dir/${trial}_scout_node.txt" 2>&1 &
scout_pid=$!
sleep 6

SSHPASS="$SENTINEL_PASS" sshpass -e ssh -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null unime-nano@10.42.0.1 \
  "printf '%s\\n' '$SENTINEL_PASS' | sudo -S systemctl stop camera-stream.service; state=\$(systemctl is-active camera-stream.service || true); echo \$state; test \"\$state\" = inactive" \
  >"$output_dir/${trial}_sentinel_stream_stop.txt" 2>&1

set +e
SSHPASS="$SENTINEL_PASS" sshpass -e ssh -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null unime-nano@10.42.0.1 \
  "bash /tmp/drone_enhanced_lab_2cd839e_r1/tools/lab_full_node_device.sh sentinel $trial $duration" \
  >"$output_dir/${trial}_sentinel_node.txt" 2>&1
sentinel_exit=$?
wait "$scout_pid"
scout_exit=$?
set -e
restore_stream
trap - EXIT
echo "trial=$trial sentinel_exit=$sentinel_exit scout_exit=$scout_exit"
if [ "$sentinel_exit" -ne 0 ] || [ "$scout_exit" -ne 0 ]; then
  exit 1
fi
