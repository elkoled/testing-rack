#!/usr/bin/env python3
"""Add an idle background to the installed AGNOS broker; never become a client."""
import hashlib
import os
from pathlib import Path
import sys

STOCK = Path('/usr/comma/magic.py')
SUPPORTED = 'c4416e66b127b31c17d08e6723ad46d12af7683e56626512d66c708b5f347ac9'


def integrate(source):
  if hashlib.sha256(source).hexdigest() != SUPPORTED:
    raise ValueError('AGNOS display broker changed; using stock broker')
  text = source.decode()
  old = '''    if not clients and need_background:
      need_background = False
      show_background(tex, pos)

    try:
      client, _ = server.accept()
    except Exception:
      continue

    need_background = True'''
  new = '''    idle_background.set_idle(not clients)
    try:
      client, _ = server.accept()
    except socket.timeout:
      if not clients:
        idle_background.draw(tex, pos, show_background)
      continue
    except Exception:
      continue

    idle_background.set_idle(False)
    need_background = True'''
  if text.count(old) != 1:
    raise ValueError('Unexpected broker loop')
  return text.replace(old, new)


def main():
  try:
    code = compile(integrate(STOCK.read_bytes()), str(STOCK), 'exec')
    from idle import IdleBackground
    background = IdleBackground(Path(__file__).parent)
  except Exception as exc:
    print(f'Rack background unavailable: {exc}', flush=True)
    os.execv(sys.executable, [sys.executable, '-u', str(STOCK)])
  # Client acceptance, descriptor handoff and updater handling remain AGNOS's.
  exec(code, {'__name__': '__main__', '__file__': str(STOCK),
              'idle_background': background})


if __name__ == '__main__':
  main()
