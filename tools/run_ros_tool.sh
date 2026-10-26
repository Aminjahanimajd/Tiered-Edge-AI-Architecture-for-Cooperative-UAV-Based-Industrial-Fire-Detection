#!/bin/sh
set -e

if [ "$#" -lt 3 ]; then
    echo "usage: run_ros_tool.sh INSTALL_PREFIX PROJECT_ROOT PYTHON_TOOL [ARGS...]" >&2
    exit 2
fi

install_prefix="$1"
project_root="$2"
python_tool="$3"
shift 3

. "${install_prefix}/setup.sh"
PYTHONPATH="${project_root}/src:${PYTHONPATH:-}"
export PYTHONPATH
exec python3 "${project_root}/${python_tool}" "$@"
