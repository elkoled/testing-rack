import ast
from pathlib import Path
import socket
import tempfile
import types
import unittest

from idle import gpu_state, reservation_text
from launch import integrate


class DisplayTests(unittest.TestCase):
  def test_reservation_expiry_and_no_false_availability(self):
    self.assertEqual(reservation_text(None, 's', 100), 'Reservation unknown')
    self.assertEqual(reservation_text((0, {'s': {'owner': None}}), 's', 46), 'Reservation unknown')
    self.assertEqual(reservation_text((10, {}), 's', 11), 'Reservation unknown')
    self.assertEqual(reservation_text((10, {'s': {}}), 's', 11), 'Reservation unknown')
    self.assertEqual(reservation_text((10, {'s': 'malformed'}), 's', 11), 'Reservation unknown')
    self.assertEqual(reservation_text((10, {'s': {'owner': 'Jenkins'}}), 's', 11), 'Reserved: Jenkins')
    self.assertEqual(reservation_text((10, {'s': {'owner': None}}), 's', 11), 'Available')

  def test_gpu_live_speed_and_disconnect(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      self.assertEqual(gpu_state(root)[1], 'gray')
      dev = root / '4-1'
      dev.mkdir()
      for key, value in {'idVendor': '3801', 'idProduct': '0001', 'speed': '5000'}.items():
        (dev / key).write_text(value)
      self.assertEqual(gpu_state(root), ('GPU 5 Gbps', 'green'))
      (dev / 'speed').write_text('12')
      self.assertEqual(gpu_state(root), ('GPU 12 Mbps', 'orange'))
      (dev / 'idVendor').unlink()
      self.assertEqual(gpu_state(root)[1], 'gray')

  def test_unknown_broker_fails_closed(self):
    with self.assertRaises(ValueError):
      integrate(b'changed AGNOS version')

  def test_real_broker_loop_prioritizes_clients(self):
    # Exercise the actual transformed loop with a live, then disconnected client.
    source = (Path(__file__).parent / 'fixtures/magic.py').read_bytes()
    tree = ast.parse(integrate(source))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    loop = main.body[-1]
    self.assertIsInstance(loop, ast.While)
    code = compile(ast.fix_missing_locations(ast.Module(body=[loop], type_ignores=[])), '<broker-loop>', 'exec')
    events = []
    class End(BaseException):
      pass
    class Thread:
      alive = True
      def __init__(self, target, args, daemon):
        self.args = args
      def start(self): events.append('handed off')
      def is_alive(self): return self.alive
      def join(self): pass
    class Server:
      count = 0
      def accept(self):
        self.count += 1
        if self.count == 1:
          raise socket.timeout()
        if self.count == 2:
          events.append('accepted')
          return object(), None
        if self.count == 3:
          Thread.alive = False
          raise socket.timeout()
        if self.count == 4:
          raise socket.timeout()
        raise End()
    idle = types.SimpleNamespace(set_idle=lambda idle: events.append(('idle', idle)),
                                 draw=lambda *args: events.append('draw'))
    env = dict(clients=set(), server=Server(), socket=socket, threading=types.SimpleNamespace(Thread=Thread),
               idle_background=idle, tex=None, pos=None, show_background=None, handle_client=None, drm_master=1)
    with self.assertRaises(End):
      exec(code, env)
    accepted = events.index('accepted')
    self.assertEqual(events[accepted + 1:accepted + 4], [('idle', False), 'handed off', ('idle', False)])
    self.assertEqual(events.count('draw'), 2)  # initial idle, then client disconnection


if __name__ == '__main__':
  unittest.main()
