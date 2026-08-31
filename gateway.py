#!/usr/bin/env python3
"""Restricted gateway selector. It never offers a gateway shell."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import re

DIRECT_RE = re.compile(
    r"([1-9A-HJ-NP-Za-km-z]{12})-(NUT[0-9]+)(?: (.+))?$"
)
PREVIOUS_RE = re.compile(
    r"(NUT[0-9]+)-([0123456789ABCDEFGHJKMNPQRSTVWXYZ]{4})-([0123456789ABCDEFGHJKMNPQRSTVWXYZ]{4})-([0123456789ABCDEFGHJKMNPQRSTVWXYZ]{4})-([0123456789ABCDEFGHJKMNPQRSTVWXYZ]{4})$"
)
LEGACY_RE = re.compile(r"r\.([A-Za-z0-9_-]{22})\.(NUT[0-9]+)$")


def request(base: str, path: str, capability: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "X-Testing-Rack-Capability": capability,
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(
        base + path, data=data, headers=headers, method="POST" if data else "GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.load(response)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Reservation unavailable or expired: {exc}") from None


def keep_active(stop: threading.Event, service: str, capability: str, device: str):
    while not stop.wait(60):
        try:
            request(service, "/api/gateway/resolve", capability, {"device": device})
        except SystemExit:
            return


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--service", default="http://localhost:80")
    parser.add_argument("--identity", default="/etc/testing-rack/device_key")
    parser.add_argument("--authorize-only", action="store_true")
    args = parser.parse_args()
    original = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    access = os.environ.get("R")
    if access:
        match = DIRECT_RE.fullmatch(access)
        if not match or match.group(3) is not None:
            raise SystemExit("Invalid rack access selector.")
        capability, device, _ = match.groups()
        remote_command = original or None
        previous = legacy = None
    else:
        match, previous, legacy = (
            DIRECT_RE.fullmatch(original),
            PREVIOUS_RE.fullmatch(original),
            LEGACY_RE.fullmatch(original),
        )
        if match:
            capability, device, remote_command = match.groups()
        elif previous:
            device, *groups = previous.groups()
            capability = "".join(groups)
            remote_command = None
        elif legacy:
            capability, device = legacy.groups()
            remote_command = None
        else:
            raise SystemExit("Usage: ssh rack@chestnut 7Km3P9xQvT2w-NUT001")
    if remote_command and re.fullmatch(r"-i\s+\S+", remote_command):
        remote_command = None
    target = request(
        args.service, "/api/gateway/resolve", capability, {"device": device}
    )
    if target["health"] != "ready":
        print(f"Warning: {device} is {target['health']}.", file=sys.stderr)
    print(
        f"{target.get('display_name', 'testing-rack')} · {device}",
        file=sys.stderr,
    )
    if remote_command in {"gpu_power:on", "gpu_power:off", "ftdi:reset"}:
        raise SystemExit(
            subprocess.run(
                [
                    "sudo",
                    "-n",
                    "/usr/bin/python3",
                    "/opt/testing-rack/actions.py",
                    device,
                    remote_command,
                ]
            ).returncode
        )
    if args.authorize_only:
        print(
            json.dumps(
                {
                    "status": "authorized",
                    "device": device,
                    "mode": "hardware-disabled",
                }
            )
        )
        return
    else:
        socket_path = Path("/var/lib/testing-rack-gateway/connections") / device
        connection = []
        if socket_path.exists():
            try:
                checked = subprocess.run(
                    [
                        "ssh",
                        "-S",
                        str(socket_path),
                        "-O",
                        "check",
                        f"comma@comma-{target['serial']}",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1,
                )
                if checked.returncode == 0:
                    connection = ["-S", str(socket_path)]
            except (OSError, subprocess.TimeoutExpired):
                pass
        stop = threading.Event()
        heartbeat = threading.Thread(
            target=keep_active,
            args=(stop, args.service, capability, device),
            daemon=True,
        )
        heartbeat.start()
        try:
            completed = subprocess.run(
                [
                    "ssh",
                    *connection,
                    "-i",
                    args.identity,
                    "-o",
                    "IdentitiesOnly=yes",
                    "-o",
                    "ClearAllForwardings=yes",
                    f"comma@comma-{target['serial']}",
                    *([remote_command] if remote_command else []),
                ]
            )
        finally:
            stop.set()
            heartbeat.join(timeout=1)
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
