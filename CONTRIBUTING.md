# Contributing

Keep changes focused and preserve the public contract in
[web/openapi.json](web/openapi.json). Put API workflow details there rather than
maintaining a second guide or discovery endpoint.

## Development

Requires Python 3.12, `uv`, Node.js, OpenSSH client tools, and a Chromium browser.

```sh
uv sync --frozen
./tests.sh
```

The gate checks JavaScript and installer syntax, application/API tests, virtual
SSH integration, device-display tests, state-machine properties, browser
workflows, and whitespace. Application branch coverage must be at least 80%.
The successful run writes `release-gate-report.json` (ignored by Git).
`tests.sh` installs Chromium if Google Chrome is unavailable. On a fresh Linux
host, browser system dependencies can be installed with
`uv run playwright install --with-deps chromium`.

Tests use temporary reservation state and simulated SSH devices. Run the full
gate one at a time: its acceptance server uses local port 18877. Do not point
`tests/browser.py` at a production rack; it creates and releases reservations.

Focused checks:

```sh
uv run python -m unittest tests.test_app tests.test_api -v
uv run python -m unittest tests.test_gateway tests.test_ssh -v
uv run python -m unittest discover -s device_display -p 'test_*.py' -v
```

`scripts/campaign.py` is an optional local fuzz campaign, not part of the normal
gate. It creates its own service and accepts explicit duration, rate, worker,
and report arguments. See `uv run python scripts/campaign.py --help`.

## Code layout

| Path | Responsibility |
| --- | --- |
| `app.py` | Configuration, reservation state, HTTP API, static files |
| `gateway.py` | Forced SSH command, token validation, session lifetime |
| `warm.py` | Private SSH connections and device connection health |
| `actions.py` | Per-device power/reset actions |
| `web/` | UI, stylesheet, and OpenAPI contract |
| `deploy/` | Rack-PC installer, systemd units, SSH and sudo policies |
| `device_display/` | AGNOS idle screen integration and its tests |
| `tests/`, `scripts/test.py` | Local test fixtures and lifecycle gate |

Keep runtime configuration, credentials, generated reports, and scratch
checkouts separate from source changes. Check `git status` before committing.
