#!/usr/bin/env bash
# Extract a verified archive into a new Scout deployment directory.

set -euo pipefail

archive=${1:?archive path required}
expected_sha256=${2:?expected SHA-256 required}
target=${3:?new target directory required}

if [ -e "$target" ]; then
  echo "refusing to overwrite existing target: $target" >&2
  exit 3
fi
actual_sha256=$(sha256sum "$archive" | awk '{print $1}')
echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "archive=$archive"
echo "archive_sha256=$actual_sha256"
echo "target=$target"
if [ "$actual_sha256" != "$expected_sha256" ]; then
  echo "archive hash mismatch" >&2
  exit 4
fi
mkdir -p "$target"
tar -xzf "$archive" -C "$target"
chmod +x \
  "$target/tools/lab_build_ros.sh" \
  "$target/tools/run_scout_rebuild_validation.sh"
find "$target" -type f -print | sort >"$target/deployed_files.txt"
echo "deployed_file_count=$(wc -l < "$target/deployed_files.txt")"
echo "finished_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "status=PASS_ISOLATED_DEPLOYMENT"
