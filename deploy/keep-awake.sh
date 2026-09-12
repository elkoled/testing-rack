#!/usr/bin/env bash
# Run as root on a provisioned rack device. Independent of openpilot and Params.
set -euo pipefail

[[ $(id -u) == 0 ]]
python3 - <<'PY'
import json
import socket
from pathlib import Path

config = json.loads(Path('/data/rack-display/config.json').read_text())
assert config['name'] in {f'NUT{i:03d}' for i in range(1, 11)}
assert socket.gethostname() == 'comma-' + config['serial']
PY

read_only=false
if awk '$2 == "/" {print $4}' /proc/mounts | tr ',' '\n' | grep -qx ro
then
  read_only=true
  mount -o remount,rw /
fi
restore_mount() {
  if "$read_only"; then mount -o remount,ro /; fi
}
trap restore_mount EXIT

systemctl mask --now power_monitor.service poweroff.target
sync
