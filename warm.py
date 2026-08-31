#!/usr/bin/env python3
"""Keep one private SSH transport open for each configured device."""

import argparse
import signal
import subprocess
import time
from pathlib import Path

from app import Config


def command(device: dict[str, str], identity: str, socket_dir: Path) -> list[str]:
    return [
        "ssh",
        "-MN",
        "-i",
        identity,
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "ClearAllForwardings=yes",
        "-o",
        "ConnectTimeout=3",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=2",
        "-o",
        "ControlMaster=yes",
        "-o",
        "ControlPersist=no",
        "-S",
        str(socket_dir / device["name"]),
        f"comma@comma-{device['serial']}",
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/testing-rack/config.json")
    parser.add_argument("--identity", default="/etc/testing-rack/device_key")
    parser.add_argument(
        "--socket-dir", default="/var/lib/testing-rack-gateway/connections"
    )
    args = parser.parse_args()
    config = Config.load(Path(args.config))
    socket_dir = Path(args.socket_dir)
    socket_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    stopping = False
    processes: dict[str, subprocess.Popen] = {}

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        for device in config.devices:
            process = processes.get(device["name"])
            if process is None or process.poll() is not None:
                (socket_dir / device["name"]).unlink(missing_ok=True)
                processes[device["name"]] = subprocess.Popen(
                    command(device, args.identity, socket_dir),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        time.sleep(1)
    for process in processes.values():
        process.terminate()
    for process in processes.values():
        try:
            process.wait(3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
