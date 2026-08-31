import http.client
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import signal
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def wait_port(port):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.02)
    raise RuntimeError("server did not start")


class HttpApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.state = root / "state"
        cls.secret = root / "secret"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "app.py"),
                "init",
                "--state",
                str(cls.state),
                "--secret",
                str(cls.secret),
            ],
            check=True,
            capture_output=True,
        )
        prefix = [sys.executable]
        if __import__("os").environ.get("TESTING_RACK_COVERAGE"):
            prefix += [
                "-m",
                "coverage",
                "run",
                "--parallel-mode",
                "--branch",
                "--source=app",
            ]
        cls.process = subprocess.Popen(
            prefix
            + [
                str(ROOT / "app.py"),
                "serve",
                "--state",
                str(cls.state),
                "--secret",
                str(cls.secret),
                "--port",
                "8876",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        wait_port(8876)

    @classmethod
    def tearDownClass(cls):
        cls.process.send_signal(signal.SIGINT)
        cls.process.wait(timeout=3)
        cls.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("localhost", 8876, timeout=3)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        result = (response.status, dict(response.getheaders()), data)
        connection.close()
        return result

    def assert_json_error(self, result, status, code):
        self.assertEqual(result[0], status)
        self.assertEqual(json.loads(result[2])["error"], code)
        self.assertEqual(result[1]["Cache-Control"], "no-store")
        self.assertEqual(result[1]["X-Content-Type-Options"], "nosniff")

    def test_security_headers_and_public_state(self):
        status, headers, body = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(
            len(json.loads(body)["devices"]),
            len(json.loads((ROOT / "config.json").read_text())["devices"]),
        )
        for name in (
            "Cache-Control",
            "X-Content-Type-Options",
            "X-Frame-Options",
            "Content-Security-Policy",
            "Referrer-Policy",
        ):
            self.assertIn(name, headers)

    def test_unsupported_methods_are_consistent_json(self):
        for method in ("PUT", "PATCH", "OPTIONS"):
            with self.subTest(method=method):
                self.assert_json_error(
                    self.request(method, "/api/state"), 405, "method_not_allowed"
                )
        status, headers, body = self.request("HEAD", "/")
        self.assertEqual((status, body), (405, b""))
        self.assertEqual(headers["Content-Length"], "0")

    def test_post_requires_json_content_type(self):
        body = json.dumps(
            {
                "nickname": "alex",
                "count": 1,
                "duration_minutes": 60,
                "idempotency_key": "http-content-key-001",
            }
        )
        self.assert_json_error(
            self.request(
                "POST", "/api/reservations", body, {"Content-Type": "text/plain"}
            ),
            415,
            "unsupported_media_type",
        )

    def test_malformed_and_bounded_bodies(self):
        cases = [
            (b"{", {"Content-Type": "application/json"}, 400, "invalid_json"),
            (b"[]", {"Content-Type": "application/json"}, 400, "invalid_body"),
            (b"{}", {"Content-Type": "application/json"}, 400, "invalid_fields"),
            (
                b"{}",
                {"Content-Type": "application/json", "Content-Length": "9000"},
                413,
                "body_too_large",
            ),
        ]
        for body, headers, status, code in cases:
            with self.subTest(code=code):
                self.assert_json_error(
                    self.request("POST", "/api/reservations", body, headers),
                    status,
                    code,
                )

    def test_paths_and_capability_boundaries(self):
        self.assert_json_error(
            self.request("GET", "/api/devices/NUT999"), 404, "not_found"
        )
        self.assert_json_error(
            self.request("GET", "/api/reservations/current"), 403, "invalid_capability"
        )
        self.assert_json_error(
            self.request("DELETE", "/api/reservations/current"),
            403,
            "invalid_capability",
        )
        self.assert_json_error(self.request("GET", "/../config.json"), 404, "not_found")


if __name__ == "__main__":
    unittest.main()
