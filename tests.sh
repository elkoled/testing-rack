#!/bin/sh
set -eu
cd "$(dirname "$0")"
command -v python3 >/dev/null
command -v node >/dev/null
command -v google-chrome >/dev/null
command -v ssh >/dev/null
command -v ssh-keygen >/dev/null
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -q -r requirements-test.txt -r requirements-gateway.txt
exec .venv/bin/python release_gate.py
