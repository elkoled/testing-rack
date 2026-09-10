"""Low-frequency background drawing, only when the AGNOS broker has no clients."""
import json
from pathlib import Path
import socket
import threading
import time
import urllib.request


def reservation_text(snapshot, serial, now):
  if not snapshot or now - snapshot[0] > 45:
    return 'Reservation unknown'
  record = snapshot[1].get(serial)
  if not isinstance(record, dict) or 'owner' not in record:
    return 'Reservation unknown'
  owner = record.get('owner')
  return 'Available' if owner is None else 'Reserved: ' + str(owner)


def gpu_state(root=Path('/sys/bus/usb/devices')):
  speeds = []
  for device in root.iterdir():
    try:
      ids = tuple(int((device / key).read_text(), 16) for key in ('idVendor', 'idProduct'))
      if ids in ((0x3801, 1), (0xADD1, 1)):
        speeds.append(int((device / 'speed').read_text()))
    except (OSError, ValueError):
      continue
  if not speeds:
    return ('GPU disconnected', 'gray')
  speed = min(speeds)
  return (f'GPU {speed / 1000:g} Gbps' if speed >= 1000 else f'GPU {speed} Mbps',
          'green' if speed >= 5000 else 'orange')


class IdleBackground:
  def __init__(self, root):
    self.root = root
    self.config = json.loads((root / 'config.json').read_text())
    if socket.gethostname() != 'comma-' + self.config['serial']:
      raise ValueError('Rack identity mismatch')
    self.idle = threading.Event()
    self.snapshot = None
    self.last = None
    self.next_check = 0.0
    self.font = None
    self.icons = {}
    self.was_idle = False
    self.failed = False
    threading.Thread(target=self.poll, daemon=True, name='rack-reservation').start()

  def poll(self):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while True:
      self.idle.wait()
      try:
        with opener.open(self.config['reservation_url'], timeout=2) as response:
          data = response.read(65537)
        if len(data) > 65536:
          raise ValueError('Oversized reservation response')
        doc = json.loads(data)
        if doc.get('fresh') is True and isinstance(doc.get('devices'), dict):
          self.snapshot = (time.monotonic(), doc['devices'])
        else:
          self.snapshot = None
      except Exception:
        # Keep the last observation for at most 45 seconds; never claim availability on failure.
        pass
      time.sleep(15)

  def set_idle(self, idle):
    if idle:
      if not self.was_idle:
        self.last = None
        self.next_check = 0.0
      self.idle.set()
    else:
      self.idle.clear()
    self.was_idle = idle

  def draw(self, original_texture, original_position, fallback, power_screen):
    if self.failed:
      if self.last != 'fallback':
        fallback(original_texture, original_position)
        self.last = 'fallback'
      return
    now = time.monotonic()
    if now < self.next_check:
      return
    self.next_check = now + 2
    try:
      if self._draw(now):
        # Preserve the stock background's screen wake after rendering, including
        # when the last client left the panel asleep. The broker gates this on idle.
        power_screen()
    except Exception as exc:
      print(f'Rack background disabled: {exc}', flush=True)
      self.failed = True
      fallback(original_texture, original_position)
      self.last = 'fallback'

  def _draw(self, now):
    import pyray as rl
    gpu = gpu_state()
    reservation = reservation_text(self.snapshot, self.config['serial'], now)
    state = (gpu, reservation)
    if state == self.last:
      return
    if self.font is None:
      self.font = rl.load_font_ex(str(self.root / 'font.ttf'), 100, None, 0)
      if not self.font.texture.id:
        raise RuntimeError('Font did not load')
      for color in ('green', 'orange'):
        icon = rl.load_texture(str(self.root / f'chestnut_{color}.png'))
        if not icon.id:
          raise RuntimeError(f'{color} GPU icon did not load')
        self.icons[color] = icon
    width, height = rl.get_screen_width(), rl.get_screen_height()
    colors = {'green': rl.Color(70, 220, 120, 255), 'orange': rl.Color(255, 170, 50, 255),
              'gray': rl.Color(150, 150, 150, 255)}

    def text(value, y, size, color):
      value = ''.join(c if c.isprintable() else ' ' for c in value)[:100]
      size *= height
      measured = rl.measure_text_ex(self.font, value, size, 0).x
      if measured > width * .92:
        size *= width * .92 / measured
      x = (width - rl.measure_text_ex(self.font, value, size, 0).x) / 2
      rl.draw_text_ex(self.font, value, rl.Vector2(x, height * y), size, 0, color)

    rl.begin_drawing()
    try:
      rl.clear_background(rl.BLACK)
      text(self.config['name'], .03, .24, rl.WHITE)
      text(f"{self.config['row'].upper()} ROW / POSITION {self.config['position']}", .29, .10, rl.WHITE)
      # Match testing-rack's .device.ready span and .device.reserved span colors.
      reservation_color = (rl.Color(86, 226, 107, 255) if reservation == 'Available' else
                           rl.Color(237, 206, 117, 255) if reservation.startswith('Reserved: ') else
                           rl.Color(150, 150, 150, 255))
      text(reservation, .44, .12, reservation_color)
      text(self.config['serial'], .60, .09, rl.WHITE)
      text(f"{self.config['strip'].capitalize()} strip / outlet {self.config['outlet']}", .72, .075, rl.WHITE)
      text(gpu[0], .85, .10, colors[gpu[1]])
      if gpu[1] in self.icons:
        icon = self.icons[gpu[1]]
        # Match the home screen: green 54x40, orange 68x40, preserving aspect ratio.
        scale = 40 / icon.height
        rl.draw_texture_ex(icon, rl.Vector2(width - icon.width * scale - 16, height - 40 - 12),
                           0, scale, rl.WHITE)
    finally:
      rl.end_drawing()
    self.last = state
    print(f"RACK_IDLE {self.config['name']} {gpu[0]} {reservation}", flush=True)
    return True
