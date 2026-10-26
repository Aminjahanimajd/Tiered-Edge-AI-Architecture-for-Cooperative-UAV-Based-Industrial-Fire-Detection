#!/usr/bin/env bash
set -eu
echo '--- host pycuda ---'
python3 - <<'PY'
import json
import pycuda
import pytools
import sys
print(pycuda.__file__)
print(pytools.__file__)
print(json.dumps(sys.path))
PY
echo '--- container paths ---'
docker run --rm --runtime nvidia dustynv/ros:foxy-ros-base-l4t-r32.7.1 \
  python3 -c 'import json,sys; print(json.dumps(sys.path))'
