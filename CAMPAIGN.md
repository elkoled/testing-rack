# Red-team campaign

Date: 2026-08-31

The campaign ran only against localhost services, temporary state, temporary
secrets, and virtual devices. It did not contact production or rack hardware.

## Bounds

- 30 minutes sustained runtime
- 20 HTTP requests per second maximum
- 2 HTTP fuzz workers
- 2 child processes maximum
- 8 KiB request body maximum

## Results

- 35,959 HTTP requests
- 26,403 invariant and security checks
- 28 complete randomized regression rounds
- 0 failures after fixes

Each regression round covered the reservation state machine, concurrency,
restart and persistence, virtual SSH authorization, remote commands, device
actions, malformed HTTP, and real Chrome desktop and mobile lifecycles.

## Findings

1. `TRACE` used the standard Python HTTP response instead of the consistent
   JSON 405 response and omitted application security headers. It now reuses
   the existing method-not-allowed handler.
2. Invalid UTF-8 in a JSON request raised `UnicodeDecodeError` and closed the
   connection without a response. It now returns the existing `invalid_json`
   response.

Both findings have focused regression tests.

Run another bounded campaign with:

```sh
.venv/bin/python scripts/campaign.py --hours 10 --rate 20 --workers 2 --report /tmp/testing-rack-campaign.json
```
