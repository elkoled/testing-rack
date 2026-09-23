#!/usr/bin/env python3
"""Run on the rack PC with its existing device credentials; serial deployment."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

root = Path(__file__).parent
for config in json.loads((root / 'inventory.json').read_text()):
  if config['name'] not in sys.argv[1:]:
    continue
  config['reservation_url'] = 'http://192.168.62.201:8766/reservations'
  key = 'setup_key' if config['serial'] in ('ba3f5545', 'de2e7866', '95940f7f') else 'device_key'
  ssh = ['sudo', '-n', '-u', 'testing-rack', 'ssh', '-i', '/etc/testing-rack/' + key,
         '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'UserKnownHostsFile=/dev/null',
         '-o', 'StrictHostKeyChecking=no', 'comma@comma-' + config['serial']]
  buf = io.BytesIO()
  with tarfile.open(fileobj=buf, mode='w') as tar:
    for name in ('launch.py', 'idle.py', 'install_device.py', 'magic-rack-display.conf', 'screen-calibration-panel.conf'):
      tar.add(root / name, arcname=name)
    for color in ('green', 'orange'):
      name = f'chestnut_{color}.png'
      tar.add(root / 'assets' / name, arcname=name)
    content = json.dumps(config).encode()
    info = tarfile.TarInfo('config.json')
    info.size = len(content)
    tar.addfile(info, io.BytesIO(content))
  subprocess.run(ssh + ['mkdir -p /data/rack-display-install && tar -xf - -C /data/rack-display-install'],
                 input=buf.getvalue(), check=True, timeout=30)
  result = subprocess.run(ssh + ['sudo -n /usr/local/venv/bin/python /data/rack-display-install/install_device.py'],
                          capture_output=True, text=True, timeout=45)
  print(config['name'], result.stdout, result.stderr, flush=True)
  result.check_returncode()
