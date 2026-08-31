import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from actions import run_action
from app import Config


class ActionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "config.json"
        path.write_text(
            json.dumps(
                {
                    "gateway_host": "rack",
                    "gateway_port": 22,
                    "idle_timeout_minutes": 60,
                    "max_devices_per_reservation": 2,
                    "devices": [
                        {
                            "name": "NUT001",
                            "device_type": "four",
                            "serial": "00000001",
                            "ftdi_serial": "FTDI0001",
                            "gpu_power_switch": "upper_1",
                        },
                        {
                            "name": "NUT002",
                            "device_type": "four",
                            "serial": "00000002",
                        },
                    ],
                }
            )
        )
        self.config = Config.load(path)
        self.lock_dir = Path(self.tmp.name) / "locks"

    def tearDown(self):
        self.tmp.cleanup()

    def test_supported_actions_are_abstract(self):
        for action in ("gpu_power:on", "gpu_power:off", "ftdi:reset"):
            with self.subTest(action=action):
                runner = mock.Mock(
                    return_value=subprocess.CompletedProcess([], returncode=0)
                )
                result = run_action(
                    self.config, "NUT001", action, runner, self.lock_dir
                )
                self.assertEqual(
                    result, {"device": "NUT001", "action": action, "status": "ok"}
                )
                self.assertNotIn("00000001", json.dumps(result))
                self.assertNotIn("FTDI0001", json.dumps(result))

    def test_missing_and_unknown_actions_fail_closed(self):
        for device, action in (
            ("NUT002", "gpu_power:on"),
            ("NUT002", "ftdi:reset"),
            ("NUT001", "gpu_power:reboot"),
        ):
            with self.subTest(device=device, action=action), self.assertRaises(ValueError):
                run_action(self.config, device, action, lock_dir=self.lock_dir)

    def test_backend_failure_is_redacted(self):
        runner = mock.Mock(return_value=subprocess.CompletedProcess([], returncode=1))
        with self.assertRaisesRegex(RuntimeError, "hardware action failed"):
            run_action(
                self.config, "NUT001", "gpu_power:on", runner, self.lock_dir
            )


if __name__ == "__main__":
    unittest.main()
