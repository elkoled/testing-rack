#!/usr/bin/env python3
"""One-command, fail-fast lifecycle gate for testing_rack."""

import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv/bin/python"
PORT = 18877
results = []


def run(name, command, env=None):
    started = time.monotonic()
    process = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, env=env)
    results.append(
        {
            "name": name,
            "passed": process.returncode == 0,
            "seconds": round(time.monotonic() - started, 3),
            "output": (process.stdout + process.stderr)[-4000:],
        }
    )
    if process.returncode:
        raise RuntimeError(f"{name} failed\n{results[-1]['output']}")


def wait_port():
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("localhost", PORT), 0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("acceptance server did not start")


def main():
    process = None
    try:
        run("syntax", ["node", "--check", "web/app.js"])
        run("installer-syntax", ["bash", "-n", "deploy/install.sh"])
        run("coverage-erase", [str(PY), "-m", "coverage", "erase"])
        coverage_env = {**os.environ, "TESTING_RACK_COVERAGE": "1"}
        run(
            "unit-api-virtual",
            [
                str(PY),
                "-m",
                "coverage",
                "run",
                "--parallel-mode",
                "--branch",
                "--source=app",
                "-m",
                "unittest",
                "-v",
                "tests/test_app.py",
                "tests/test_actions.py",
                "tests/test_api.py",
                "tests/test_gateway.py",
                "tests/test_ssh.py",
                "tests/test_warm.py",
            ],
            coverage_env,
        )
        run("coverage-combine", [str(PY), "-m", "coverage", "combine"])
        run("coverage", [str(PY), "-m", "coverage", "report", "--fail-under=80"])
        run(
            "model-state-machine",
            [str(PY), "-m", "unittest", "-v", "tests/test_model.py"],
        )
        with tempfile.TemporaryDirectory(prefix="testing-rack-gate-") as directory:
            state = Path(directory) / "state.json"
            secret = Path(directory) / "secret"
            run(
                "initialize",
                [
                    str(PY),
                    "app.py",
                    "init",
                    "--state",
                    str(state),
                    "--secret",
                    str(secret),
                ],
            )
            process = subprocess.Popen(
                [
                    str(PY),
                    "app.py",
                    "serve",
                    "--state",
                    str(state),
                    "--secret",
                    str(secret),
                    "--bind",
                    "localhost",
                    "--port",
                    str(PORT),
                ],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
            wait_port()
            run(
                "real-chrome",
                [str(PY), "tests/browser.py", "--url", f"http://localhost:{PORT}"],
            )
        run("diff-whitespace", ["git", "diff", "--check"])
    except Exception as exc:
        report = {"passed": False, "error": str(exc), "checks": results}
        print(json.dumps(report, indent=2))
        return 1
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    report = {"passed": True, "checks": results, "finished_at": time.time()}
    (ROOT / "release-gate-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
