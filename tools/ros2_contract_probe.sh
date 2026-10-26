#!/usr/bin/env bash
set -eo pipefail

source /opt/ros/jazzy/setup.bash
source /workspace/ros2_ws/install/setup.bash
set -u

probe_output="$(mktemp)"
cleanup() {
  rm -f "$probe_output"
}
trap cleanup EXIT

timeout 15 ros2 topic echo --once /contract_probe \
  drone_enhanced_interfaces/msg/HazardAlert >"$probe_output" &
listener_pid=$!
sleep 2
ros2 topic pub --once /contract_probe \
  drone_enhanced_interfaces/msg/HazardAlert \
  "{experiment_id: jazzy_contract_probe, trial_id: no_vehicle_001, event_id: event_001, source_device: simulator_host, hazard_type: fire, confidence: 0.75, temporal_count: 3, source_frame_monotonic_ns: 100, alert_monotonic_ns: 200, model_sha256: '0000000000000000000000000000000000000000000000000000000000000000', target_u: 0.5, target_v: 0.5, bbox_width: 0.1, bbox_height: 0.1, frame_width: 640, frame_height: 480}"
wait "$listener_pid"
grep -q "event_id: event_001" "$probe_output"
grep -q "source_device: simulator_host" "$probe_output"
grep -q "0000000000000000000000000000000000000000000000000000000000000000" "$probe_output"
cat "$probe_output"
