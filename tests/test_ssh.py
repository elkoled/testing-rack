import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import signal
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def wait_port(port: int, host: str = "localhost") -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"port {port} did not open")


class VirtualRackIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.config, self.state, self.secret, self.host_key = (
            root / "config.json",
            root / "state.json",
            root / "secret",
            root / "host_key",
        )
        self.config.write_text(
            json.dumps(
                {
                    "gateway_host": "localhost",
                    "gateway_port": 23022,
                    "idle_timeout_minutes": 60,
                    "max_devices_per_reservation": 3,
                    "devices": [
                        {
                            "name": "NUT001",
                            "device_type": "four",
                            "serial": "00000001",
                            "ftdi_serial": "FTDI0001",
                        },
                        # Deliberately absent: verifies graceful device-unavailable behavior.
                        {
                            "name": "NUT002",
                            "device_type": "four",
                            "serial": "00000002",
                            "ftdi_serial": "FTDI0002",
                        },
                        {
                            "name": "NUT003",
                            "device_type": "four",
                            "serial": "00000003",
                            "ftdi_serial": "FTDI0003",
                        },
                    ],
                }
            )
        )
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "app.py"),
                "init",
                "--config",
                str(self.config),
                "--state",
                str(self.state),
                "--secret",
                str(self.secret),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.host_key)],
            check=True,
        )
        service_prefix = [sys.executable]
        if __import__("os").environ.get("TESTING_RACK_COVERAGE"):
            service_prefix += [
                "-m",
                "coverage",
                "run",
                "--parallel-mode",
                "--branch",
                "--source=app",
            ]
        self.processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "tests/device.py"),
                    "--count",
                    "3",
                    "--port",
                    "23000",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
            subprocess.Popen(
                service_prefix
                + [
                    str(ROOT / "app.py"),
                    "serve",
                    "--config",
                    str(self.config),
                    "--state",
                    str(self.state),
                    "--secret",
                    str(self.secret),
                    "--port",
                    "8875",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
        ]
        wait_port(23000, "localhost")
        wait_port(8875)
        self.processes.append(
            subprocess.Popen(
                [
                    str(ROOT / ".venv/bin/python"),
                    str(ROOT / "tests/ssh_server.py"),
                    "--bind",
                    "localhost",
                    "--port",
                    "23022",
                    "--host-key",
                    str(self.host_key),
                    "--service",
                    "http://localhost:8875",
                    "--virtual-device-port",
                    "23000",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        wait_port(23022)

    def tearDown(self):
        for process in reversed(getattr(self, "processes", [])):
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
        for process in reversed(getattr(self, "processes", [])):
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        self.tmp.cleanup()

    def request(self, path, method="GET", body=None, token=None, key=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if key:
            headers["Idempotency-Key"] = key
        with urllib.request.urlopen(
            urllib.request.Request(
                "http://localhost:8875" + path,
                data=data,
                headers=headers,
                method=method,
            )
        ) as response:
            return json.load(response)

    def ssh(self, argument):
        return subprocess.run(
            [
                "ssh",
                "-F",
                "/dev/null",
                "-p",
                "23022",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "rack@localhost",
                argument,
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )

    def test_keyless_access_and_release_closes_active_session(self):
        lease = self.request(
            "/api/reservations",
            "POST",
            {"name": "auth-matrix", "count": 1},
            key="auth-matrix-key-001",
        )
        selector = f"{lease['token']}-NUT001"

        connected = self.ssh(selector)
        self.assertEqual(connected.returncode, 0, connected.stderr)

        active = subprocess.Popen(
            [
                "ssh",
                "-F",
                "/dev/null",
                "-p",
                "23022",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "rack@localhost",
                f"{selector} hold",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(0.3)
        self.assertIsNone(active.poll())
        self.request("/api/reservation", "DELETE", token=lease["token"])
        _, stderr = active.communicate(timeout=3)
        self.assertEqual(active.returncode, 3)
        self.assertIn("Reservation released or expired", stderr)

    def test_authorization_reachability_failure_and_release(self):
        lease = self.request(
            "/api/reservations",
            "POST",
            {
                "name": "virtual-alex",
                "count": 2,
            },
            key="virtual-integration-key-01",
        )
        capability = lease["token"]
        healthy = self.ssh(f"{capability}-NUT001")
        self.assertEqual(
            healthy.returncode,
            0,
            f"argument={capability}-NUT001 stdout={healthy.stdout!r} stderr={healthy.stderr!r}",
        )
        payload = json.loads(healthy.stdout)
        self.assertEqual(payload["target_identity"]["serial"], "00000001")
        self.assertEqual(payload["target_identity"]["hardware"], "four")

        commanded = self.ssh(f"{capability}-NUT001 printf agent-ok")
        self.assertEqual(commanded.returncode, 0, commanded.stderr)
        self.assertEqual(json.loads(commanded.stdout)["remote_command"], "printf agent-ok")

        unavailable = self.ssh(f"{capability}-NUT002")
        self.assertEqual(unavailable.returncode, 4)
        self.assertIn("reservation remains active", unavailable.stderr)
        self.assertEqual(
            self.request("/api/reservation", token=capability)["devices"],
            ["NUT001", "NUT002"],
        )

        outside_scope = self.ssh(f"{capability}-NUT003")
        self.assertEqual(outside_scope.returncode, 3)
        self.assertIn("not reserved by this token", outside_scope.stderr)
        random_token = self.ssh("7Km3P9xQvT2w-NUT001")
        self.assertEqual(random_token.returncode, 3)
        leading_hyphen = self.ssh("r.-AAAAAAAAAAAAAAAAAAAAA.NUT001")
        self.assertEqual(leading_hyphen.returncode, 2, leading_hyphen.stderr)

        self.request("/api/reservation", "DELETE", token=capability)
        released = self.ssh(f"{capability}-NUT001")
        self.assertEqual(released.returncode, 3)
        self.assertIn("released, or expired", released.stderr)


if __name__ == "__main__":
    unittest.main()
