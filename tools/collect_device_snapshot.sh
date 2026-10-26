#!/bin/sh
#
# Collect a read-only software/hardware snapshot from Sentinel or Scout.
#
# Usage:
#   sh collect_device_snapshot.sh ROLE OUTPUT_DIR [FILE_TO_HASH ...]
#
# Examples:
#   sh collect_device_snapshot.sh sentinel /tmp/sentinel_snapshot \
#     /workspace/ros2_ws/sentinel_v1.engine \
#     /workspace/ros2_ws/sentinel_ros2_node.py
#
#   sh collect_device_snapshot.sh scout /tmp/scout_snapshot \
#     /home/root/colcon_ws/best.tflite \
#     /home/root/colcon_ws/scout_ros2_node.py
#
# The script does not change services, packages, clocks, network settings, ROS
# configuration, or model files. It creates only OUTPUT_DIR and a compressed
# archive beside it. Review network and history outputs before sharing them.

set -u

ROLE=${1:-}
OUTPUT_DIR=${2:-}

if [ -z "$ROLE" ] || [ -z "$OUTPUT_DIR" ]; then
    echo "Usage: $0 ROLE OUTPUT_DIR [FILE_TO_HASH ...]" >&2
    exit 2
fi

case "$ROLE" in
    sentinel|scout)
        ;;
    *)
        echo "ROLE must be 'sentinel' or 'scout'." >&2
        exit 2
        ;;
esac

shift 2

if [ -e "$OUTPUT_DIR" ]; then
    echo "Refusing to overwrite existing output: $OUTPUT_DIR" >&2
    exit 3
fi

mkdir -p "$OUTPUT_DIR"

run_capture() {
    NAME=$1
    shift
    {
        echo "# command: $*"
        echo "# utc_start: $(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || true)"
        "$@"
        STATUS=$?
        echo
        echo "# exit_status: $STATUS"
    } >"$OUTPUT_DIR/$NAME.txt" 2>&1
}

run_shell_capture() {
    NAME=$1
    COMMAND=$2
    {
        echo "# shell command: $COMMAND"
        echo "# utc_start: $(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || true)"
        sh -c "$COMMAND"
        STATUS=$?
        echo
        echo "# exit_status: $STATUS"
    } >"$OUTPUT_DIR/$NAME.txt" 2>&1
}

{
    echo "role=$ROLE"
    echo "snapshot_utc=$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || true)"
    echo "hostname=$(hostname 2>/dev/null || true)"
    echo "user=$(id -un 2>/dev/null || true)"
    echo "working_directory=$(pwd)"
} >"$OUTPUT_DIR/snapshot_metadata.txt"

run_capture "uname" uname -a
run_capture "os_release" sh -c 'cat /etc/os-release 2>/dev/null'
run_capture "identity" id
run_capture "uptime" uptime
run_capture "date_utc" date -u
run_capture "date_local" date
run_capture "timedatectl" timedatectl status
run_capture "lscpu" lscpu
run_capture "memory" free -h
run_capture "disk" df -h
run_capture "mounts" mount
run_capture "processes" ps auxww
run_capture "kernel_modules" lsmod
run_capture "usb_devices" lsusb
run_capture "pci_devices" lspci
run_capture "video_devices" sh -c 'ls -l /dev/video* 2>/dev/null'
run_capture "network_addresses" ip address show
run_capture "network_routes" ip route show
run_capture "network_links" ip -s link show
run_capture "listening_sockets" sh -c 'ss -lntup 2>/dev/null || netstat -lntup 2>/dev/null'

run_shell_capture "command_locations" \
    'for c in python3 pip3 ros2 docker trtexec nvcc tegrastats voxl-version voxl-inspect-services voxl-inspect-cam; do command -v "$c" 2>/dev/null || true; done'
run_capture "python_version" python3 --version
run_capture "pip_version" python3 -m pip --version
run_capture "pip_freeze" python3 -m pip freeze
run_capture "ros_distro" sh -c 'printf "%s\n" "${ROS_DISTRO:-unset}"'
run_capture "ros_domain_id" sh -c 'printf "%s\n" "${ROS_DOMAIN_ID:-unset}"'
run_capture "rmw_implementation" sh -c 'printf "%s\n" "${RMW_IMPLEMENTATION:-unset}"'
run_capture "ros_nodes" ros2 node list
run_capture "ros_topics_types" ros2 topic list -t
run_capture "ros_services" ros2 service list -t
run_capture "ros_interfaces" ros2 interface list
run_capture "docker_version" docker version
run_capture "docker_info" docker info
run_capture "docker_images" docker images --digests --no-trunc
run_capture "docker_containers" docker ps -a --no-trunc
run_capture "cuda_version" nvcc --version
run_capture "tensorrt_version" trtexec --version
run_capture "jetson_release" sh -c 'cat /etc/nv_tegra_release 2>/dev/null'
run_capture "nvidia_packages" sh -c \
    'dpkg-query -W 2>/dev/null | grep -Ei "nvidia|cuda|cudnn|tensorrt|libnvinfer"'
run_capture "voxl_version" voxl-version
run_capture "voxl_services" voxl-inspect-services
run_capture "systemd_services" systemctl --no-pager --all --type=service

if [ "$ROLE" = "sentinel" ]; then
    run_capture "jetson_clocks_status" sh -c \
        'jetson_clocks --show 2>/dev/null || true'
    run_capture "nvpmodel" sh -c \
        'nvpmodel -q --verbose 2>/dev/null || true'
    run_capture "v4l2_devices" sh -c \
        'v4l2-ctl --list-devices 2>/dev/null || true'
    run_capture "mavlink_processes" sh -c \
        'ps auxww | grep -Ei "mavlink|mavproxy|mavros|px4" | grep -v grep'
else
    run_capture "voxl_camera_services" sh -c \
        'ps auxww | grep -Ei "voxl.*camera|camera.*server" | grep -v grep'
    run_capture "voxl_pipes" sh -c \
        'find /run/mpa -maxdepth 3 -type p -o -type s -o -type f 2>/dev/null'
fi

{
    echo "# Explicit file inventory"
    for FILE_PATH in "$@"; do
        echo
        echo "## $FILE_PATH"
        if [ -e "$FILE_PATH" ]; then
            stat "$FILE_PATH" 2>&1 || true
            if command -v sha256sum >/dev/null 2>&1; then
                sha256sum "$FILE_PATH" 2>&1 || true
            elif command -v openssl >/dev/null 2>&1; then
                openssl dgst -sha256 "$FILE_PATH" 2>&1 || true
            else
                echo "No SHA-256 utility found."
            fi
        else
            echo "MISSING"
        fi
    done
} >"$OUTPUT_DIR/explicit_file_inventory.txt"

if command -v sha256sum >/dev/null 2>&1; then
    (
        cd "$OUTPUT_DIR" || exit 1
        find . -type f ! -name snapshot_sha256.txt -print0 \
            | sort -z \
            | xargs -0 sha256sum
    ) >"$OUTPUT_DIR/snapshot_sha256.txt" 2>/dev/null || true
fi

ARCHIVE_PATH="${OUTPUT_DIR}.tar.gz"
tar -czf "$ARCHIVE_PATH" -C "$(dirname "$OUTPUT_DIR")" "$(basename "$OUTPUT_DIR")"

echo "Snapshot directory: $OUTPUT_DIR"
echo "Archive: $ARCHIVE_PATH"
echo "Review network-related files before sharing or committing."
