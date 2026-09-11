# Rack assignment audit

Observed on 2026-09-11 from `chestnut` (192.168.62.201).

## Result

All ten configured FTDI adapters were enumerated on the rack PC. All ten devices
reported the expected hostname and kernel boot serial, matching their installed
rack-display configuration. Every device reported one GPU at 5000 Mbps (5 Gbps).
Device names, serials, physical positions, and power assignments agree between
rack configuration, display inventory, installed displays, and the power helper.

| Device | Device serial | Configured FTDI (present) | Rack USB path | GPU outlet | Observed GPU serial |
| --- | --- | --- | --- | --- | --- |
| NUT001 | 557d5c3a | DK0CFVDW | 1-1.1 | lower_1 | b7169169 |
| NUT002 | d292bc85 | DK0CG2LJ | 1-1.2 | lower_2 | a6ce0fd9 |
| NUT003 | 528f306f | DK0CFPB6 | 1-1.3 | lower_3 | f9a70b65 |
| NUT004 | 4117bfee | DK0CFVLA | 1-1.4.1 | lower_4 | f89015cd |
| NUT005 | d05bb90f | DK0CFZ4T | 1-1.4.2 | lower_5 | 5849970b |
| NUT006 | 178e6b20 | DK0CFV87 | 1-1.4.3 | upper_1 | b0785807 |
| NUT007 | 96035a74 | DK0CFPQE | 1-1.4.4.2 | upper_3 | 738702d2 |
| NUT008 | ba3f5545 | DK0CGFB6 | 1-1.4.4.1 | upper_2 | 7c3c93f8 |
| NUT009 | de2e7866 | DK0CGTCH | 1-1.4.4.3 | upper_4 | 46abf125 |
| NUT010 | 95940f7f | DK0CFUGS | 1-1.4.4.4 | upper_5 | 58c0b69f |

NUT007 and NUT008 use upper outlets 3 and 2 respectively. Their FTDI USB paths
also follow outlet order rather than physical position. Do not renumber these
assignments based on enumeration order.

The deployed inventory reserves NUT008, NUT009, and NUT010 for Jenkins. The
checkout was missing the NUT008 fixed reservation; it has been aligned with the
observed configuration.

## Method and limits

The scan read rack USB sysfs descriptors, the deployed inventory, and the power
helper's mapping without executing the helper. It then read hostnames, kernel
boot arguments, display configurations, and USB descriptors over SSH on each
device. The initial pass used one connection at a time, ten devices, an eight-second
per-device timeout, no automatic retries, and a 120-second overall limit.

NUT010's shared SSH transport timed out. One separate direct SSH inspection using
the existing setup credential succeeded within a 15-second limit. Its device and
GPU identities were verified through that direct connection.

This verifies adapter presence and agreement of recorded assignments. It does
**not independently prove which GPU each FTDI reset wire controls**. The adapters
are attached to the rack PC, while GPUs enumerate on the devices; those two USB
inventories contain no common identity field proving the electrical pairing.
The FTDI debug helper changes CBUS GPIO levels even when merely opened, so it was
not invoked. No resets, power changes, flashing, or reservation changes were made.
End-to-end reset-wire and power-outlet verification requires a separate,
coordinated hardware test or physical inspection.

This is a dated observation, not live health information. Operational inventory
remains in [`config.json`](../config.json) and
[`device_display/inventory.json`](../device_display/inventory.json).
