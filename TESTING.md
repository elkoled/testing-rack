# Testing

`./tests.sh` is the mandatory pre-deployment gate. A
failed or skipped row means the build is not releasable.

| Contract | Automated evidence |
|---|---|
| Atomic one/many-device allocation with no overlap | unit races, 100-device/20-user scale test, Hypothesis state machine |
| One live reservation per normalized Name | unit concurrency and two independent browser profiles |
| Retry after an uncertain response | idempotency unit/model tests and conflicting reuse rejection |
| Release, simultaneous release, expiry and reallocation | unit concurrency, model test, browser lifecycle |
| Crash/restart durability and corrupt/missing state | restart and fail-closed unit tests |
| Interrupted disk commit | injected final-commit failure where memory and current disk remain unchanged |
| Capability cannot access another device | virtual SSH gateway integration |
| Dead device degrades without losing the lease | virtual four unreachable-device integration |
| Released/random/malformed credentials fail | virtual SSH gateway integration and API boundary tests |
| Multiple tabs and rapid clicks converge | real Chrome interleaving tests and storage-event regression |
| Plain URL/new tab restores ownership on the same PC profile | real Chrome localStorage lifecycle tests |
| Old browser crypto APIs and clipboard denial | real Chrome feature-removal and permission-denial tests |
| Desktop/mobile readability and JS runtime errors | real Chrome at 1440x1000 and 390x844, page-error assertions |
| Malformed HTTP, methods, paths, sizes and security headers | HTTP protocol tests |
| 20 concurrent users / 100 devices | deterministic scale test |

Production acceptance additionally verifies the installed file hashes, hardened
systemd/SSH configuration, persistence across a real service restart, HTTP,
and an exact generated `ssh rack@chestnut -oSetEnv=RACK_ACCESS=TOKEN-NUTxxx` command in
hardware-disabled mode. Physical rack targets are never contacted by this gate.

Threat boundary: without company SSO, a Name is a cooperative identity rather
than proof of a person. Capability possession authorizes a lease. The gateway,
not device IP secrecy, is the enforcement point. Production rack network ACLs
must prevent clients from bypassing it before hardware mode can be enabled.
