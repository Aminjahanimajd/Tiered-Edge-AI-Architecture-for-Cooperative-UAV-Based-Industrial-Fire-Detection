#!/usr/bin/env bash
set -eu

if (( $# != 4 )); then
  echo "usage: SSHPASS=... $0 ARCHIVE USER HOST REMOTE_DIRECTORY" >&2
  exit 2
fi

archive=$1
remote_user=$2
remote_host=$3
remote_directory=$4
archive_name=$(basename "$archive")
expected_sha=$(sha256sum "$archive" | awk '{print $1}')

ssh_options=(
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
)

sshpass -e ssh "${ssh_options[@]}" "$remote_user@$remote_host" \
  "test ! -e '$remote_directory' && mkdir -p '$remote_directory'"
sshpass -e scp "${ssh_options[@]}" "$archive" \
  "$remote_user@$remote_host:$remote_directory/$archive_name"
remote_sha=$(
  sshpass -e ssh "${ssh_options[@]}" "$remote_user@$remote_host" \
    "sha256sum '$remote_directory/$archive_name' | cut -d ' ' -f1"
)
if [ "$remote_sha" != "$expected_sha" ]; then
  echo "archive hash mismatch: $remote_sha != $expected_sha" >&2
  exit 1
fi
sshpass -e ssh "${ssh_options[@]}" "$remote_user@$remote_host" \
  "tar -xzf '$remote_directory/$archive_name' -C '$remote_directory' && find '$remote_directory' -maxdepth 2 -type f | wc -l"
printf 'deployed_utc=%s\nhost=%s\nremote_directory=%s\narchive_sha256=%s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$remote_host" "$remote_directory" "$expected_sha"
