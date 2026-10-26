#!/usr/bin/env bash
set -eu

if (( $# != 2 )); then
  echo "usage: SSHPASS=... $0 USER HOST" >&2
  exit 2
fi

remote_user=$1
remote_host=$2

sshpass -e ssh \
  -o ConnectTimeout=10 \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  "$remote_user@$remote_host" '
set -u
printf "snapshot_utc="; date -u +%Y-%m-%dT%H:%M:%SZ
printf "identity="; id -un
printf "hostname="; hostname
printf "kernel="; uname -a
printf "uptime="; uptime -p
printf "root_disk="; df -h / | tail -1
printf "memory="; free -m | tr "\n" ";"; echo
printf "addresses="; ip -o -4 address show | tr "\n" ";"; echo
printf "routes="; ip -4 route | tr "\n" ";"; echo
printf "os_release="; tr "\n" ";" < /etc/os-release; echo
printf "python="; python3 --version 2>&1 || true
printf "ros_distro="; printf "%s\n" "${ROS_DISTRO:-unset}"
printf "docker="; docker --version 2>&1 || true
printf "camera_devices="; ls -l /dev/video* 2>&1 | tr "\n" ";"; echo
printf "serial_devices="; ls -l /dev/ttyACM* /dev/ttyUSB* 2>&1 | tr "\n" ";"; echo
printf "relevant_processes="; ps -eo pid,lstart,cmd | grep -E "ros|dds|yolo|python|camera|mav|voxl" | grep -v grep | tr "\n" ";"; echo
'
