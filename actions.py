#!/usr/bin/env python3
"""Optional Chestnut hardware actions. Backend identifiers never leave this process."""

import argparse
import fcntl
import json
import subprocess
from pathlib import Path
from typing import Callable

from app import Config


POWER_PYTHON = "/home/batman/.venvs/kasa-patterns/bin/python3"
POWER_HELPER = "/home/batman/tici_test_scripts/chestnut/rack_power_target.py"
FTDI_PYTHON = "/home/batman/asm2464pd-firmware/.venv/bin/python"
FTDI_HELPER = "/home/batman/asm2464pd-firmware/ftdi_debug.py"
LOCK_DIR = Path("/var/lib/testing-rack-gateway/actions")
Runner = Callable[..., subprocess.CompletedProcess]


def run_action(
    config: Config,
    name: str,
    action: str,
    runner: Runner = subprocess.run,
    lock_dir: Path = LOCK_DIR,
) -> dict[str, str]:
    device = next((item for item in config.devices if item["name"] == name), None)
    if device is None:
        raise ValueError("unknown device")
    if action in ("gpu_power:on", "gpu_power:off"):
        if "gpu_power_switch" not in device:
            raise ValueError("GPU power is not installed")
        command = [
            "runuser",
            "-u",
            "batman",
            "--",
            POWER_PYTHON,
            POWER_HELPER,
            device["serial"],
            action.removeprefix("gpu_power:"),
        ]
        timeout = 45
    elif action == "ftdi:reset":
        if "ftdi_serial" not in device:
            raise ValueError("FTDI reset is not installed")
        command = [
            "runuser",
            "-u",
            "batman",
            "--",
            FTDI_PYTHON,
            FTDI_HELPER,
            "-d",
            f"ftdi://ftdi:ft-x:{device['ftdi_serial']}/1",
            "-r",
            "-n",
        ]
        timeout = 10
    else:
        raise ValueError("unsupported action")
    lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (lock_dir / name).open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another hardware action is running") from exc
        result = runner(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError("hardware action failed")
    return {"device": name, "action": action, "status": "ok"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("device")
    parser.add_argument("action")
    parser.add_argument("--config", default="/etc/testing-rack/config.json")
    args = parser.parse_args()
    try:
        result = run_action(Config.load(Path(args.config)), args.device, args.action)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"device": args.device, "status": "error", "message": str(exc)}))
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
