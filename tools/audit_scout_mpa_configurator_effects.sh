#!/usr/bin/env bash
# Audit the effects of an accidental voxl-configure-mpa-to-ros2 invocation.

set -u

echo "audit_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "--- configurator source ---"
cat /usr/bin/voxl-configure-mpa-to-ros2

echo "--- Micro DDS service state ---"
systemctl is-enabled voxl-microdds-agent.service 2>&1 || true
systemctl is-active voxl-microdds-agent.service 2>&1 || true
systemctl show voxl-microdds-agent.service \
  -p ActiveEnterTimestamp -p NRestarts -p ExecMainStatus

echo "--- ROS profile ---"
stat /home/root/.profile.d/source_foxy_setup.sh /home/root/.bashrc 2>/dev/null || true
cat /home/root/.profile.d/source_foxy_setup.sh 2>/dev/null || true

echo "--- empy runtime ---"
python3 - <<'PY'
import em
print('version={}'.format(getattr(em, '__version__', 'unknown')))
print('file={}'.format(getattr(em, '__file__', 'unknown')))
PY

echo "--- recently modified relevant files ---"
find \
  /home/root/.profile.d \
  /etc/systemd/system \
  /usr/local/lib/python3.6/dist-packages \
  -xdev -mmin -15 -printf '%TY-%Tm-%TdT%TH:%TM:%TS %p\n' 2>/dev/null \
  | sort | tail -200

echo "status=PASS_EFFECT_AUDIT"
