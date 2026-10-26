#!/usr/bin/env bash
set -euo pipefail

output_dir=${1:?output directory required}
count=${2:-100}
mkdir -p "$output_dir"
: "${SENTINEL_PASS:?SENTINEL_PASS required}"
: "${SCOUT_PASS:?SCOUT_PASS required}"

for index in 1 2 3; do
  trial=$(printf 'ros-rtt-%02d' "$index")
  scout_log="$output_dir/${trial}_scout_responder.txt"
  sentinel_log="$output_dir/${trial}_sentinel_initiator.txt"
  SSHPASS="$SCOUT_PASS" sshpass -e ssh \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    root@10.42.0.125 \
    "bash /tmp/drone_enhanced_lab_2cd839e_r1/tools/lab_ros_roundtrip_device.sh scout responder $trial $count" \
    >"$scout_log" 2>&1 &
  responder_pid=$!
  sleep 3
  set +e
  SSHPASS="$SENTINEL_PASS" sshpass -e ssh \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    unime-nano@10.42.0.1 \
    "bash /tmp/drone_enhanced_lab_2cd839e_r1/tools/lab_ros_roundtrip_device.sh sentinel initiator $trial $count" \
    >"$sentinel_log" 2>&1
  initiator_exit=$?
  wait "$responder_pid"
  responder_exit=$?
  set -e
  echo "$trial initiator_exit=$initiator_exit responder_exit=$responder_exit"
  if [ "$initiator_exit" -ne 0 ] || [ "$responder_exit" -ne 0 ]; then
    exit 1
  fi
done
