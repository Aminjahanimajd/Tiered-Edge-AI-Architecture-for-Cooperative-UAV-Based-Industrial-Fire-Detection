#!/bin/sh
set -e

if [ "$#" -ne 3 ]; then
    echo "usage: check_ros_install.sh INSTALL_PREFIX NODE PROJECT_ROOT" >&2
    exit 2
fi

install_prefix="$1"
node="$2"
project_root="$3"

. "${install_prefix}/setup.sh"
PYTHONPATH="${project_root}/src:${PYTHONPATH:-}"
export PYTHONPATH

ros2 interface show drone_enhanced_interfaces/msg/HazardAlert
ros2 interface show drone_enhanced_interfaces/msg/HazardVerdict
ros2 interface show drone_enhanced_interfaces/msg/HazardDecision
python3 "${project_root}/tools/check_ros_imports.py" "${node}"
