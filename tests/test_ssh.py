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
        self.client_key = root / "xx_key"
        self.other_key = root / "other_key"
        for key in (self.client_key, self.other_key):
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
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
        self.agent_socket = root / "agent.sock"
        self.processes.append(
            subprocess.Popen(
                ["ssh-agent", "-D", "-a", str(self.agent_socket)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        deadline = time.monotonic() + 5
        while not self.agent_socket.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        subprocess.run(
            ["ssh-add", str(self.client_key)],
            check=True,
            capture_output=True,
            env={"SSH_AUTH_SOCK": str(self.agent_socket)},
        )
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
                    "--authorized-key",
                    str(self.client_key) + ".pub",
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

    def ssh(self, argument, identity=None, after_command=()):
        identity_args = ["-i", str(identity)] if identity else []
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
                "IdentityAgent=none",
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                *identity_args,
                "rack@localhost",
                argument,
                *after_command,
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )

    def ssh_tokens(self, tokens, agent=False):
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
                f"IdentityAgent={self.agent_socket if agent else 'none'}",
                "-o",
                f"IdentitiesOnly={'no' if agent else 'yes'}",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                *tokens,
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )

    def test_openssh_authentication_matrix(self):
        lease = self.request(
            "/api/reservations",
            "POST",
            {"name": "auth-matrix", "count": 1},
            key="auth-matrix-key-001",
        )
        selector = f"{lease['token']}-NUT001"

        no_key = self.ssh_tokens(["rack@localhost", selector])
        self.assertEqual(no_key.returncode, 255)
        self.assertIn("Permission denied (publickey)", no_key.stderr)

        unrelated = self.ssh_tokens(
            ["-i", str(self.other_key), "rack@localhost", selector]
        )
        self.assertEqual(unrelated.returncode, 255)

        explicit = self.ssh_tokens(
            ["-i", str(self.client_key), "rack@localhost", selector]
        )
        self.assertEqual(explicit.returncode, 0, explicit.stderr)

        direct_style = self.ssh_tokens(
            ["rack@localhost", "-i", str(self.client_key), selector]
        )
        self.assertEqual(direct_style.returncode, 0, direct_style.stderr)

        coworker_failure = self.ssh_tokens(
            ["rack@localhost", selector, "-i", str(self.client_key)]
        )
        self.assertEqual(coworker_failure.returncode, 255)
        self.assertIn("Permission denied (publickey)", coworker_failure.stderr)

        agent = self.ssh_tokens(["rack@localhost", selector], agent=True)
        self.assertEqual(agent.returncode, 0, agent.stderr)

        setenv = f"-oSetEnv=R={selector}"
        setenv_explicit = self.ssh_tokens(
            ["rack@localhost", setenv, "-i", str(self.client_key)]
        )
        self.assertEqual(setenv_explicit.returncode, 0, setenv_explicit.stderr)

        setenv_agent = self.ssh_tokens(["rack@localhost", setenv], agent=True)
        self.assertEqual(setenv_agent.returncode, 0, setenv_agent.stderr)

        setenv_no_key = self.ssh_tokens(["rack@localhost", setenv])
        self.assertEqual(setenv_no_key.returncode, 255)

        setenv_command = self.ssh_tokens(
            [
                "rack@localhost",
                setenv,
                "-i",
                str(self.client_key),
                "printf agent-ok",
            ]
        )
        self.assertEqual(setenv_command.returncode, 0, setenv_command.stderr)
        self.assertEqual(
            json.loads(setenv_command.stdout)["remote_command"], "printf agent-ok"
        )

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
        healthy = self.ssh(f"{capability}-NUT001", self.client_key)
        self.assertEqual(
            healthy.returncode,
            0,
            f"argument={capability}-NUT001 stdout={healthy.stdout!r} stderr={healthy.stderr!r}",
        )
        payload = json.loads(healthy.stdout)
        self.assertEqual(payload["target_identity"]["serial"], "00000001")
        self.assertEqual(payload["target_identity"]["hardware"], "four")

        commanded = self.ssh(
            f"{capability}-NUT001 printf agent-ok", self.client_key
        )
        self.assertEqual(commanded.returncode, 0, commanded.stderr)
        self.assertEqual(json.loads(commanded.stdout)["remote_command"], "printf agent-ok")

        unavailable = self.ssh(f"{capability}-NUT002", self.client_key)
        self.assertEqual(unavailable.returncode, 4)
        self.assertIn("reservation remains active", unavailable.stderr)
        self.assertEqual(
            self.request("/api/reservation", token=capability)["devices"],
            ["NUT001", "NUT002"],
        )

        outside_scope = self.ssh(f"{capability}-NUT003", self.client_key)
        self.assertEqual(outside_scope.returncode, 3)
        self.assertIn("not part of reservation", outside_scope.stderr)
        random_token = self.ssh("7Km3P9xQvT2w-NUT001", self.client_key)
        self.assertEqual(random_token.returncode, 3)
        leading_hyphen = self.ssh(
            "r.-AAAAAAAAAAAAAAAAAAAAA.NUT001", self.client_key
        )
        self.assertEqual(leading_hyphen.returncode, 3, leading_hyphen.stderr)

        self.request("/api/reservation", "DELETE", token=capability)
        released = self.ssh(f"{capability}-NUT001", self.client_key)
        self.assertEqual(released.returncode, 3)
        self.assertIn("released, or expired", released.stderr)


if __name__ == "__main__":
    unittest.main()
