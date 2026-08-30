#!/bin/sh
set -eu
cd "$(dirname "$0")"
command -v python3 >/dev/null
command -v node >/dev/null
command -v ssh >/dev/null
command -v ssh-keygen >/dev/null
if [ ! -x .venv/bin/python ]
then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -q -r requirements-dev.txt
if ! command -v google-chrome >/dev/null
then
  .venv/bin/playwright install chromium
fi
exec .venv/bin/python scripts/test.py
