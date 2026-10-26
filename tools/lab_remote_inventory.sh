#!/usr/bin/env bash
set -eu

if (( $# != 3 )); then
  echo "usage: SSHPASS=... $0 ROLE USER HOST" >&2
  exit 2
fi

role=$1
remote_user=$2
remote_host=$3

sshpass -e ssh \
  -o ConnectTimeout=10 \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  "$remote_user@$remote_host" bash -s -- "$role" <<'REMOTE'
set -u
role=$1
printf 'inventory_utc='; date -u +%Y-%m-%dT%H:%M:%SZ
printf 'role=%s\n' "$role"
printf '%s\n' '--- docker ---'
docker ps -a --no-trunc 2>&1 || true
printf '%s\n' '--- system services ---'
if [ "$role" = sentinel ]; then
  systemctl is-active camera-stream.service 2>&1 || true
  systemctl status camera-stream.service --no-pager -l 2>&1 | head -40 || true
  printf '%s\n' '--- known sentinel artifacts ---'
  for path in \
    /home/unime-nano/ros2_ws/sentinel_v1.engine \
    /home/unime-nano/ros2_ws/sentinel_ros2_node.py \
    /home/unime-nano/ros2_ws/swarm_vision_logs.csv \
    /home/unime-nano/Drone_Enhanced; do
    if [ -e "$path" ]; then
      stat -c '%n|%s|%y|%F' "$path"
      [ -f "$path" ] && sha256sum "$path"
    else
      printf 'MISSING|%s\n' "$path"
    fi
  done
  find /home/unime-nano/Drone_Enhanced -maxdepth 4 -type f 2>/dev/null | sort | head -200
  printf '%s\n' '--- jetson runtime ---'
  dpkg-query -W 'nvidia-jetpack' 'libnvinfer*' 2>&1 || true
  nvpmodel -q 2>&1 || true
  timeout 2 tegrastats 2>&1 || true
else
  for service in voxl-camera-server voxl-mavlink-server voxl-microdds-agent voxl-px4 voxl-qvio-server voxl-vision-hub voxl-time-sync; do
    printf '%s=' "$service"; systemctl is-active "$service" 2>&1 || true
  done
  printf '%s\n' '--- known scout artifacts ---'
  for path in \
    /home/root/colcon_ws/best.tflite \
    /home/root/colcon_ws/scout_ros2_node.py \
    /home/root/colcon_ws/swarm_vision_logs.csv \
    /home/root/Drone_Enhanced; do
    if [ -e "$path" ]; then
      stat -c '%n|%s|%y|%F' "$path"
      [ -f "$path" ] && sha256sum "$path"
    else
      printf 'MISSING|%s\n' "$path"
    fi
  done
  find /home/root/Drone_Enhanced -maxdepth 4 -type f 2>/dev/null | sort | head -200
  printf '%s\n' '--- voxl versions ---'
  voxl-version 2>&1 || true
  dpkg-query -W 'voxl-*' 2>&1 | head -100 || true
fi
REMOTE
