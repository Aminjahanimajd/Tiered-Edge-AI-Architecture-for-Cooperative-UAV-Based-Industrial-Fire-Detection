#!/usr/bin/env bash
# Inspect the installed ModalAI MPA-to-ROS 2 bridge without starting it.

set -u

echo "snapshot_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "safety_state=read-only bridge inspection; no vehicle command"

bridge_root=/opt/ros/foxy/mpa_to_ros2
launch_file="$bridge_root/install/voxl_mpa_to_ros2/share/voxl_mpa_to_ros2/launch/voxl_mpa_to_ros2.launch"
executable="$bridge_root/install/voxl_mpa_to_ros2/lib/voxl_mpa_to_ros2/voxl_mpa_to_ros2_node"

echo "--- launch file ---"
sed -n '1,240p' "$launch_file" 2>/dev/null || true

echo "--- installed executable ---"
ls -l "$executable" 2>/dev/null || true
sha256sum "$executable" 2>/dev/null || true

echo "--- bridge source files ---"
find "$bridge_root/src/voxl_mpa_to_ros2" -maxdepth 4 -type f -print 2>/dev/null | sort

for source in \
  "$bridge_root/src/voxl_mpa_to_ros2/src/voxl_mpa_to_ros2_node.cpp" \
  "$bridge_root/src/voxl_mpa_to_ros2/src/main.cpp"; do
  if [ -r "$source" ]; then
    echo "file=$source"
    sed -n '1,320p' "$source"
  fi
done

echo "--- configurator ---"
ls -l /usr/bin/voxl-configure-mpa-to-ros2 2>/dev/null || true
/usr/bin/voxl-configure-mpa-to-ros2 --help 2>&1 || true

echo "status=PASS_READ_ONLY_BRIDGE_INSPECTION"
