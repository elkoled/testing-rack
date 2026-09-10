#!/usr/bin/env python3
"""Install on one device. Leave an active AGNOS display broker running."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

from launch import SUPPORTED


def display_busy():
  # Accepted connections and queued clients both prevent a broker restart.
  connections = subprocess.check_output(['ss', '-xanH'], text=True)
  for line in connections.splitlines():
    if '/tmp/drmfd.sock' in line:
      fields = line.split()
      if fields[1] != 'LISTEN' or int(fields[2]):
        return True
  for proc in Path('/proc').glob('[0-9]*'):
    try:
      args = (proc / 'cmdline').read_bytes().split(b'\0')
    except OSError:
      continue
    if any(arg.endswith((b'/manager.py', b'/spinner.py')) or arg in
           (b'openpilot.selfdrive.ui.ui', b'selfdrive.ui.ui') for arg in args[:3]):
      return True
  return False


def main():
  if os.geteuid() != 0:
    raise PermissionError('Installation requires root')
  source = Path(__file__).parent
  config = json.loads((source / 'config.json').read_text())
  if socket.gethostname() != 'comma-' + config['serial']:
    raise ValueError('Device identity mismatch')
  if hashlib.sha256(Path('/usr/comma/magic.py').read_bytes()).hexdigest() != SUPPORTED:
    raise ValueError('Unsupported AGNOS display broker')
  dest = Path('/data/rack-display')
  dest.mkdir(exist_ok=True)
  for name in ('launch.py', 'idle.py', 'config.json'):
    shutil.copyfile(source / name, dest / (name + '.new'))
    os.chmod(dest / (name + '.new'), 0o644)
    os.replace(dest / (name + '.new'), dest / name)
  for color in ('green', 'orange'):
    shutil.copyfile(source / f'chestnut_{color}.png', dest / f'chestnut_{color}.png')
  shutil.copyfile('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', dest / 'font.ttf')
  # Root is normally read-only; restore its original mount mode even on failure.
  options = next(line.split()[3] for line in Path('/proc/mounts').read_text().splitlines() if line.split()[1] == '/')
  read_only = 'ro' in options.split(',')
  try:
    if read_only:
      subprocess.run(['mount', '-o', 'remount,rw', '/'], check=True)
    dropin = Path('/etc/systemd/system/magic.service.d')
    dropin.mkdir(exist_ok=True)
    target = dropin / '90-rack-display.conf'
    if target.exists() and not (dest / 'previous-dropin.conf').exists():
      shutil.copyfile(target, dest / 'previous-dropin.conf')
    shutil.copyfile(source / 'magic-rack-display.conf', target)
    subprocess.run(['sync'], check=True)
  finally:
    if read_only:
      subprocess.run(['mount', '-o', 'remount,ro', '/'], check=True)
  subprocess.run(['systemctl', 'daemon-reload'], check=True)
  before = subprocess.check_output(['systemctl', 'show', 'magic', '-p', 'MainPID', '--value'], text=True).strip()
  if display_busy():
    activation = 'pending: active display/openpilot left untouched'
  else:
    time.sleep(1)
    if display_busy():
      activation = 'pending: active display/openpilot left untouched'
    else:
      subprocess.run(['systemctl', 'restart', 'magic'], check=True)
      time.sleep(3)
      subprocess.run(['systemctl', 'is-active', '--quiet', 'magic'], check=True)
      activation = 'active'
  after = subprocess.check_output(['systemctl', 'show', 'magic', '-p', 'MainPID', '--value'], text=True).strip()
  result = {'serial': config['serial'], 'name': config['name'], 'activation': activation,
            'pid_before': before, 'pid_after': after,
            'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in dest.iterdir() if p.is_file()}}
  print(json.dumps(result))


if __name__ == '__main__':
  main()
