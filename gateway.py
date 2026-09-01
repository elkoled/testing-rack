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

SELECTOR_RE = re.compile(
    r"([1-9A-HJ-NP-Za-km-z]{12})-(NUT[0-9]+)(?: (.+))?$"
)


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


def keep_active(
    stop: threading.Event,
    revoked: threading.Event,
    service: str,
    capability: str,
    device: str,
):
    while not stop.wait(2):
        try:
            request(service, "/api/gateway/resolve", capability, {"device": device})
        except SystemExit:
            revoked.set()
            return


def close_connection(socket_path: Path, destination: str) -> None:
    subprocess.run(
        ["ssh", "-S", str(socket_path), "-O", "exit", destination],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=2,
        check=False,
    )


def forward(
    command: list[str],
    revoked: threading.Event,
    control: tuple[Path, str] | None = None,
) -> int:
    process = subprocess.Popen(command)
    while process.poll() is None:
        if revoked.wait(0.1):
            if control:
                close_connection(*control)
            process.terminate()
            try:
                process.wait(2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            print("Reservation released or expired.", file=sys.stderr)
            return 3
    return process.returncode


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--service", default="http://localhost:80")
    parser.add_argument("--identity", default="/etc/testing-rack/device_key")
    args = parser.parse_args()
    original = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    match = SELECTOR_RE.fullmatch(original)
    if not match:
        raise SystemExit("Usage: ssh rack@chestnut 7Km3P9xQvT2w-NUT001")
    capability, device, remote_command = match.groups()
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
    socket_path = Path("/var/lib/testing-rack-gateway/connections") / device
    connection = []
    control = None
    destination = f"comma@comma-{target['serial']}"
    if socket_path.exists():
        try:
            checked = subprocess.run(
                [
                    "ssh",
                    "-S",
                    str(socket_path),
                    "-O",
                    "check",
                    destination,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1,
            )
            if checked.returncode == 0:
                connection = ["-S", str(socket_path)]
                control = (socket_path, destination)
        except (OSError, subprocess.TimeoutExpired):
            pass
    stop = threading.Event()
    revoked = threading.Event()
    heartbeat = threading.Thread(
        target=keep_active,
        args=(stop, revoked, args.service, capability, device),
        daemon=True,
    )
    heartbeat.start()
    try:
        result = forward(
            [
                "ssh",
                *connection,
                "-T",
                "-i",
                args.identity,
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "ClearAllForwardings=yes",
                destination,
                *([remote_command] if remote_command else []),
            ],
            revoked,
            control,
        )
    finally:
        stop.set()
        heartbeat.join(timeout=1)
    raise SystemExit(result)


if __name__ == "__main__":
    main()
