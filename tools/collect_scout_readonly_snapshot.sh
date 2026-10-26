#!/usr/bin/env bash
# Read-only ModalAI Scout snapshot for the stationary laboratory campaign.

set -u

echo "snapshot_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "safety_state=propellers_removed; no arm, motor, or vehicle command"

echo "--- identity ---"
id
hostname
uname -a
cat /etc/os-release

echo "--- voxl version ---"
voxl-version 2>&1 || true

echo "--- network ---"
ip -4 -brief addr

echo "--- storage and memory ---"
df -h /
free -m

echo "--- thermal zones ---"
for zone in /sys/class/thermal/thermal_zone*; do
  printf '%s type=' "$zone"
  cat "$zone/type" 2>/dev/null || true
  printf '%s temperature_raw=' "$zone"
  cat "$zone/temp" 2>/dev/null || true
done

echo "--- running vehicle services ---"
systemctl --no-pager --type=service --state=running 2>/dev/null \
  | grep -Ei 'voxl|px4|camera|mavlink|dds|ros' || true

echo "--- ROS and Python runtime ---"
ls -la /opt/ros 2>/dev/null || true
python3 --version 2>&1 || true
python3 -c 'import sys; print(sys.path)' 2>&1 || true

echo "--- candidate model files ---"
find /home /data -maxdepth 5 -type f \
  \( -name '*.tflite' -o -name '*.onnx' -o -name '*.dlc' -o -name '*.pt' \) \
  -printf '%p %s bytes\n' 2>/dev/null | sort

echo "--- root project directories ---"
find /home/root -maxdepth 3 -type d 2>/dev/null | sort | head -200

echo "--- relevant processes ---"
ps -eo pid,etime,comm,args \
  | grep -Ei 'voxl|px4|ros2|dds|tflite|onnx|camera|mavlink' \
  | grep -v grep || true

echo "status=PASS_READ_ONLY_SNAPSHOT"
