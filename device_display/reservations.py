#!/usr/bin/env python3
"""Read-only, serial-keyed cache of the rack's public reservation state."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import threading
import time
import urllib.request

CONFIG = Path('/etc/testing-rack/config.json')
snapshot = None


def refresh():
  global snapshot
  opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
  while True:
    try:
      before = CONFIG.read_bytes()
      with opener.open('http://127.0.0.1/api/state', timeout=2) as response:
        data = response.read(65537)
      if len(data) > 65536 or CONFIG.read_bytes() != before:
        raise ValueError('Inventory changed or response oversized')
      inventory = {d['name']: d['serial'] for d in json.loads(before)['devices']}
      state = json.loads(data)
      by_serial = {inventory[d['name']]: {'owner': d['owner']} for d in state['devices']}
      if len(by_serial) != len(inventory):
        raise ValueError('Incomplete state')
      snapshot = (time.monotonic(), by_serial)
    except Exception:
      pass
    time.sleep(10)


class Handler(BaseHTTPRequestHandler):
  def do_GET(self):
    if self.path != '/reservations':
      self.send_error(404)
      return
    current = snapshot
    fresh = current is not None and time.monotonic() - current[0] < 30
    data = json.dumps({'fresh': fresh, 'devices': current[1] if fresh else {}}).encode()
    self.send_response(200)
    self.send_header('Content-Type', 'application/json')
    self.send_header('Cache-Control', 'no-store')
    self.send_header('Content-Length', str(len(data)))
    self.end_headers()
    self.wfile.write(data)

  def log_message(self, *args):
    pass


class Server(HTTPServer):
  def get_request(self):
    client, address = super().get_request()
    client.settimeout(2)
    return client, address


if __name__ == '__main__':
  threading.Thread(target=refresh, daemon=True).start()
  Server(('0.0.0.0', 8766), Handler).serve_forever()
