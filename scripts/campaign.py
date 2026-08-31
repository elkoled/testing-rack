#!/usr/bin/env python3
"""Bounded, isolated fuzz and red-team campaign for testing-rack."""

import argparse
import http.client
import json
import os
import random
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv/bin/python"
MAX_BODY = 8192


class Campaign:
    def __init__(self, hours: float, rate: int, workers: int, report: Path):
        self.deadline = time.monotonic() + hours * 3600
        self.rate = rate
        self.workers = workers
        self.report = report
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.counts = {"requests": 0, "checks": 0, "failures": 0, "rounds": 0}
        self.findings = []
        self.tokens = []
        self.process = None
        self.regression = None
        self.port = 0

    def record(self, key: str, amount: int = 1):
        with self.lock:
            self.counts[key] += amount

    def fail(self, label: str, detail: str):
        with self.lock:
            self.counts["failures"] += 1
            self.findings.append(
                {"at": time.time(), "label": label, "detail": detail[:2000]}
            )
        self.stop.set()

    def request(self, method, path, body=b"", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            data = response.read(MAX_BODY + 1)
            if len(data) > MAX_BODY:
                raise AssertionError("response exceeded 8 KiB")
            self.record("requests")
            return response.status, dict(response.getheaders()), data
        finally:
            connection.close()

    def check_state(self):
        status, _, raw = self.request("GET", "/api/state")
        assert status == 200
        state = json.loads(raw)
        names = [device["name"] for device in state["devices"]]
        assert len(names) == len(set(names))
        assert all("serial" not in device for device in state["devices"])
        self.record("checks")

    def valid_step(self, rng: random.Random):
        action = rng.randrange(5)
        if action < 2:
            name = f"fuzz-{uuid.uuid4().hex[:12]}"
            if rng.randrange(2):
                payload = {"name": name, "count": rng.randint(1, 10)}
            else:
                count = rng.randint(1, 4)
                devices = rng.sample([f"NUT{i:03d}" for i in range(1, 11)], count)
                payload = {"name": name, "devices": devices}
            status, _, raw = self.request(
                "POST",
                "/api/reservations",
                json.dumps(payload).encode(),
                {
                    "Content-Type": "application/json",
                    "Idempotency-Key": uuid.uuid4().hex,
                },
            )
            assert status in {201, 409}
            if status == 201:
                result = json.loads(raw)
                assert set(result["devices"]) <= set(
                    payload.get("devices", [f"NUT{i:03d}" for i in range(1, 11)])
                )
                with self.lock:
                    self.tokens.append(result["token"])
        elif action == 2:
            with self.lock:
                token = rng.choice(self.tokens) if self.tokens else "invalidtoken"
            status, _, _ = self.request(
                "GET", "/api/reservation", headers={"Authorization": f"Bearer {token}"}
            )
            assert status in {200, 403}
        elif action == 3:
            with self.lock:
                token = self.tokens.pop() if self.tokens else "invalidtoken"
            status, _, _ = self.request(
                "DELETE",
                "/api/reservation",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert status in {200, 403}
        else:
            self.check_state()

    def malformed_step(self, rng: random.Random):
        methods = ["GET", "POST", "DELETE", "PUT", "PATCH", "OPTIONS", "TRACE"]
        paths = [
            "/api/reservations",
            "/api/reservation",
            "/api/state",
            "/api/agent",
            "/api/devices/NUT001",
            "/api/devices/../state",
            "/../config.json",
            "/%2e%2e/config.json",
            "/" + "A" * rng.randint(1, 2048),
        ]
        bodies = [
            b"",
            b"{",
            b"[]",
            b"null",
            os.urandom(rng.randint(0, 256)),
            json.dumps({"name": "x", "count": -1}).encode(),
            b"x" * rng.randint(8193, 9000),
        ]
        method, path, body = rng.choice(methods), rng.choice(paths), rng.choice(bodies)
        request_headers = {
            "Content-Type": rng.choice(
                ["application/json", "text/plain", "application/octet-stream"]
            ),
            "Authorization": rng.choice(
                ["", "Bearer", "Basic xxx", "Bearer invalidtoken"]
            ),
            "Idempotency-Key": rng.choice(["", "short", uuid.uuid4().hex]),
        }
        try:
            status, headers, _ = self.request(
                method, path, body, request_headers
            )
        except Exception as exc:
            raise RuntimeError(
                f"request failed for {method} {path!r} body_bytes={len(body)} "
                f"headers={request_headers!r}: {exc!r}"
            ) from exc
        if not 200 <= status < 600:
            raise AssertionError(f"invalid status {status} for {method} {path!r}")
        if headers.get("X-Content-Type-Options") != "nosniff":
            raise AssertionError(
                f"missing security header for {method} {path!r} status={status} "
                f"headers={headers!r} body_bytes={len(body)}"
            )
        self.record("checks")

    def fuzz_worker(self, index: int):
        rng = random.Random(os.urandom(16))
        delay = self.workers / self.rate
        try:
            while not self.stop.is_set() and time.monotonic() < self.deadline:
                started = time.monotonic()
                if rng.randrange(3):
                    self.malformed_step(rng)
                else:
                    self.valid_step(rng)
                remaining = delay - (time.monotonic() - started)
                if remaining > 0:
                    self.stop.wait(remaining)
        except Exception as exc:
            self.fail(f"http-worker-{index}", repr(exc))

    def regression_worker(self):
        while not self.stop.is_set() and time.monotonic() < self.deadline:
            env = {**os.environ, "HYPOTHESIS_SEED": str(random.randrange(2**32))}
            self.regression = subprocess.Popen(
                [str(PY), "scripts/test.py"],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            while (
                self.regression.poll() is None
                and not self.stop.wait(1)
                and time.monotonic() < self.deadline
            ):
                pass
            if self.regression.poll() is None:
                self.regression.terminate()
            try:
                output, _ = self.regression.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                self.regression.kill()
                output, _ = self.regression.communicate()
            self.record("rounds")
            if self.regression.returncode and not self.stop.is_set():
                self.fail("regression", output)
                return
            self.regression = None

    def write_report(self, started: float, finished: bool):
        payload = {
            "isolated": True,
            "production_touched": False,
            "started_at": started,
            "updated_at": time.time(),
            "finished": finished,
            "bounds": {
                "requests_per_second": self.rate,
                "http_workers": self.workers,
                "max_body_bytes": MAX_BODY,
                "max_child_processes": 2,
            },
            "counts": self.counts,
            "findings": self.findings,
        }
        temporary = self.report.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n")
        temporary.replace(self.report)

    def run(self):
        started = time.time()
        with tempfile.TemporaryDirectory(prefix="testing-rack-campaign-") as directory:
            root = Path(directory)
            state, secret = root / "state.json", root / "secret"
            subprocess.run(
                [str(PY), "app.py", "init", "--state", str(state), "--secret", str(secret)],
                cwd=ROOT,
                check=True,
                capture_output=True,
            )
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                self.port = probe.getsockname()[1]
            self.process = subprocess.Popen(
                [
                    str(PY),
                    "app.py",
                    "serve",
                    "--state",
                    str(state),
                    "--secret",
                    str(secret),
                    "--bind",
                    "127.0.0.1",
                    "--port",
                    str(self.port),
                ],
                cwd=ROOT,
                stdout=(root / "server.log").open("w"),
                stderr=subprocess.STDOUT,
            )
            for _ in range(100):
                try:
                    self.check_state()
                    break
                except OSError:
                    time.sleep(0.05)
            threads = [
                threading.Thread(target=self.fuzz_worker, args=(index,), daemon=True)
                for index in range(self.workers)
            ]
            threads.append(threading.Thread(target=self.regression_worker, daemon=True))
            for thread in threads:
                thread.start()
            try:
                while not self.stop.wait(30) and time.monotonic() < self.deadline:
                    if self.process.poll() is not None:
                        self.fail("service-exit", f"exit {self.process.returncode}")
                    self.write_report(started, False)
            finally:
                self.stop.set()
                if self.regression is not None and self.regression.poll() is None:
                    self.regression.terminate()
                for thread in threads:
                    thread.join(timeout=5)
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
                self.write_report(started, True)
        return 1 if self.findings else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=10)
    parser.add_argument("--rate", type=int, default=20)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not 0 < args.hours <= 10 or not 1 <= args.rate <= 20 or not 1 <= args.workers <= 2:
        raise SystemExit("campaign bounds are invalid")
    return Campaign(args.hours, args.rate, args.workers, args.report).run()


if __name__ == "__main__":
    raise SystemExit(main())
