#!/usr/bin/env python3
"""Restricted SSH gateway for hardware-free testing_rack testing."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shlex
import urllib.error
import urllib.request
from pathlib import Path

import asyncssh


CAPABILITY_RE = re.compile(
    r"(?:[1-9A-HJ-NP-Za-km-z]{12}|[0123456789ABCDEFGHJKMNPQRSTVWXYZ]{16}|[A-Za-z0-9_-]{22})$"
)
DEVICE_RE = re.compile(r"NUT[0-9]+$")


class RestrictedServer(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return username != "rack"


def api_request(base: str, path: str, capability: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "X-Testing-Rack-Capability": capability,
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(
        base + path,
        data=data,
        headers=headers,
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        return json.load(response)


def resolve(services: list[str], capability: str, device: str):
    for service in services:
        try:
            reservation = api_request(service, "/api/reservations/current", capability)
            if device not in reservation["devices"]:
                return (
                    None,
                    f"ACCESS DENIED: {device} is not part of reservation {reservation['display_id']}.",
                )
            target = api_request(
                service, "/api/gateway/resolve", capability, {"device": device}
            )
            return (reservation, target), None
        except urllib.error.HTTPError as exc:
            if exc.code not in (403, 404):
                return None, "GATEWAY ERROR: reservation service rejected the request."
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            continue
    return None, "ACCESS DENIED: reservation is unknown, released, or expired."


async def virtual_identity(serial: str, port: int) -> dict:
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection("localhost", port), 2
    )
    try:
        writer.write(f"identity {serial}\n".encode())
        await writer.drain()
        identity = json.loads(await asyncio.wait_for(reader.readline(), 2))
        if "error" in identity:
            raise OSError(identity["error"])
        return identity
    finally:
        writer.close()
        await writer.wait_closed()


async def handle(
    process: asyncssh.SSHServerProcess,
    services: list[str],
    virtual_device_port: int | None,
) -> None:
    try:
        parts = shlex.split(process.command or "")
    except ValueError:
        parts = []
    modern = (
        re.fullmatch(r"([1-9A-HJ-NP-Za-km-z]{12})-(NUT[0-9]+)", parts[0])
        if len(parts) == 1
        else None
    )
    previous = (
        re.fullmatch(
            r"(NUT[0-9]+)-([0123456789ABCDEFGHJKMNPQRSTVWXYZ]{4}(?:-[0123456789ABCDEFGHJKMNPQRSTVWXYZ]{4}){3})",
            parts[0],
        )
        if len(parts) == 1
        else None
    )
    if modern:
        capability, device = modern.groups()
    elif previous:
        device, capability = previous.group(1), previous.group(2).replace("-", "")
    elif len(parts) == 1 and parts[0].startswith("r."):
        capability, device = parts[0][2:].rsplit(".", 1)
    else:
        process.stderr.write("Usage: 7Km3P9xQvT2w-NUT001\n")
        process.exit(2)
        return
    if not CAPABILITY_RE.fullmatch(capability) or not DEVICE_RE.fullmatch(device):
        process.stderr.write("Usage: 7Km3P9xQvT2w-NUT001\n")
        process.exit(2)
        return
    result, error = await asyncio.to_thread(resolve, services, capability, device)
    if error:
        process.stderr.write(error + "\n")
        process.exit(3)
        return
    reservation, target = result
    identity = None
    if virtual_device_port is not None:
        try:
            identity = await virtual_identity(target["serial"], virtual_device_port)
        except (OSError, TimeoutError, json.JSONDecodeError):
            process.stderr.write(
                f"DEVICE UNAVAILABLE: {target['name']} did not answer. Your reservation remains active.\n"
            )
            process.exit(4)
            return
        if identity.get("serial") != target["serial"]:
            process.stderr.write(
                f"IDENTITY MISMATCH: expected {target['serial']}; refusing access.\n"
            )
            process.exit(5)
            return
    process.stdout.write(
        json.dumps(
            {
                "status": "authorized",
                "reservation": reservation["display_id"],
                "device": target["name"],
                "health": target["health"],
                "expires_at": reservation["expires_at"],
                "mode": "virtual-device" if identity else "simulation",
                "target_identity": identity,
                "message": "Gateway reached and verified the virtual comma 4."
                if identity
                else "Gateway access works; real device forwarding remains disabled.",
            }
        )
        + "\n"
    )
    process.exit(0)


async def run(args) -> None:
    await asyncssh.create_server(
        RestrictedServer,
        args.bind,
        args.port,
        server_host_keys=[str(args.host_key)],
        process_factory=lambda process: handle(
            process, args.service, args.virtual_device_port
        ),
        encoding="utf-8",
    )
    print(
        f"restricted simulated gateway listening on {args.bind}:{args.port}", flush=True
    )
    await asyncio.Future()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="localhost")
    parser.add_argument("--port", type=int, default=22022)
    parser.add_argument("--host-key", type=Path, required=True)
    parser.add_argument("--service", action="append", default=[])
    parser.add_argument("--virtual-device-port", type=int)
    args = parser.parse_args()
    if not args.service:
        args.service = ["http://localhost:8765"]
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
