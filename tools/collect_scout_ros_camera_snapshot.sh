#!/usr/bin/env bash
# Read-only Scout ROS/MPA/camera/model inventory before any deployment change.

set -u

echo "snapshot_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "safety_state=propellers_removed; read-only inspection; no vehicle command"

echo "--- exact model hashes ---"
for model in \
  /home/root/best.onnx \
  /home/root/best_float16.tflite \
  /home/root/yolov8s.onnx \
  /home/root/colcon_ws/best.onnx \
  /home/root/colcon_ws/best.tflite \
  /home/root/colcon_ws/yolov8s.onnx; do
  if [ -f "$model" ]; then
    sha256sum "$model"
  fi
done

echo "--- workspace source inventory and hashes ---"
find /home/root/colcon_ws/src -maxdepth 8 -type f -print0 2>/dev/null \
  | sort -z | xargs -0 -r sha256sum

echo "--- MPA pipes ---"
command -v voxl-list-pipes || true
voxl-list-pipes 2>&1 || true
find /run/mpa -maxdepth 3 -printf '%M %u:%g %s %p\n' 2>/dev/null | sort

echo "--- camera server configuration ---"
for config in \
  /etc/modalai/voxl-camera-server.conf \
  /etc/modalai/voxl-streamer.conf \
  /etc/modalai/voxl-mpa-to-ros2.conf; do
  if [ -r "$config" ]; then
    echo "file=$config"
    cat "$config"
  fi
done

echo "--- relevant service definitions ---"
for service in \
  voxl-camera-server.service \
  voxl-microdds-agent.service \
  voxl-mavlink-server.service \
  voxl-px4.service \
  voxl-streamer.service; do
  systemctl cat "$service" 2>/dev/null || true
done

echo "--- ROS graph ---"
set +u
source /opt/ros/foxy/setup.bash 2>/dev/null || true
source /home/root/colcon_ws/install/setup.bash 2>/dev/null || true
set -u
timeout 15 ros2 node list 2>&1 || true
timeout 15 ros2 topic list -t 2>&1 || true

echo "--- inference runtimes ---"
python3 - <<'PY'
modules = ('tflite_runtime.interpreter', 'tensorflow', 'onnxruntime', 'cv2')
for name in modules:
    try:
        module = __import__(name, fromlist=['*'])
        print('{} version={} file={}'.format(
            name,
            getattr(module, '__version__', 'unknown'),
            getattr(module, '__file__', 'unknown'),
        ))
    except Exception as exc:
        print('{} unavailable: {}'.format(name, exc))
PY

echo "status=PASS_READ_ONLY_ROS_CAMERA_SNAPSHOT"
