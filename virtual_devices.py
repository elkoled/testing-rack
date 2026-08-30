#!/usr/bin/env python3
"""Isolated TCP stand-ins for comma 4 devices used only by the test campaign."""

from __future__ import annotations

import argparse
import asyncio
import json


async def handle(name: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
  try:
    request = await asyncio.wait_for(reader.readline(), 2)
    command = request.decode(errors="replace").strip()
    if command == "identity":
      response = {"device": name, "hardware": "comma 4", "serial": name, "state": "offroad", "virtual": True}
    else:
      response = {"device": name, "error": "unsupported command"}
    writer.write((json.dumps(response, separators=(",", ":")) + "\n").encode())
    await writer.drain()
  finally:
    writer.close()
    await writer.wait_closed()


async def run(count: int, port: int) -> None:
  servers = []
  for index in range(1, count + 1):
    name, host = f"NUT{index:03d}", f"127.77.0.{index}"
    servers.append(await asyncio.start_server(lambda r, w, n=name: handle(n, r, w), host, port))
  print(f"{count} virtual comma 4 devices listening on 127.77.0.1-{count}:{port}", flush=True)
  await asyncio.Future()


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--count", type=int, default=24)
  parser.add_argument("--port", type=int, default=23000)
  args = parser.parse_args()
  if not 1 <= args.count <= 100: raise SystemExit("count must be 1-100")
  asyncio.run(run(args.count, args.port))


if __name__ == "__main__": main()
