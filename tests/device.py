#!/usr/bin/env python3
"""Isolated TCP stand-ins for comma 4 devices used only by the test campaign."""

from __future__ import annotations

import argparse
import asyncio
import json


async def handle(
    available: set[str], reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    try:
        request = await asyncio.wait_for(reader.readline(), 2)
        command = request.decode(errors="replace").strip()
        parts = command.split()
        serial = parts[1] if len(parts) == 2 and parts[0] == "identity" else ""
        if serial in available:
            response = {
                "device": serial,
                "hardware": "comma 4",
                "serial": serial,
                "state": "offroad",
                "virtual": True,
            }
        else:
            response = {"serial": serial, "error": "device unavailable"}
        writer.write((json.dumps(response, separators=(",", ":")) + "\n").encode())
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def run(count: int, port: int) -> None:
    available = {f"{index:08x}" for index in range(1, count + 1) if index != 2}
    await asyncio.start_server(
        lambda reader, writer: handle(available, reader, writer),
        "localhost",
        port,
    )
    print(f"{len(available)} virtual comma 4 serials ready", flush=True)
    await asyncio.Future()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=24)
    parser.add_argument("--port", type=int, default=23000)
    args = parser.parse_args()
    if not 1 <= args.count <= 100:
        raise SystemExit("count must be 1-100")
    asyncio.run(run(args.count, args.port))


if __name__ == "__main__":
    main()
