#!/bin/sh
set -eu
cd "$(dirname "$0")"
command -v uv >/dev/null
command -v node >/dev/null
command -v ssh >/dev/null
command -v ssh-keygen >/dev/null
uv sync --frozen --quiet
if ! command -v google-chrome >/dev/null
then
  uv run playwright install chromium
fi
exec .venv/bin/python scripts/test.py
