# Rack assignment audit

Physically verified on 2026-09-11 from `chestnut` (192.168.62.201). NUT names, comma serials and physical positions are unchanged. The previous power and FTDI mappings were incorrect.

Each GPU outlet was switched off separately while monitoring all ten devices. Exactly one supply dropped below 3 V; it returned above 8 V after restoration. Each FTDI was reset separately with the existing normal-reset helper; exactly one GPU changed USB device number and re-enumerated.

| Device | Comma serial | GPU outlet | FTDI serial |
|---|---|---|---|
| NUT001 | `557d5c3a` | upper_1 | `DK0CFV87` |
| NUT002 | `d292bc85` | upper_2 | `DK0CGFB6` |
| NUT003 | `528f306f` | upper_3 | `DK0CFPQE` |
| NUT004 | `4117bfee` | lower_5 | `DK0CFZ4T` |
| NUT005 | `d05bb90f` | upper_5 | `DK0CFUGS` |
| NUT006 | `178e6b20` | lower_1 | `DK0CFVDW` |
| NUT007 | `96035a74` | lower_2 | `DK0CG2LJ` |
| NUT008 | `ba3f5545` | lower_3 | `DK0CFPB6` |
| NUT009 | `de2e7866` | lower_4 | `DK0CFVLA` |
| NUT010 | `95940f7f` | upper_4 | `DK0CGTCH` |

Lower outlet 6 powers the bottom-row comma devices (NUT006–010). Upper outlet 6 powers the top-row comma devices (NUT001–005). Both were power-cycled; changed boot IDs confirmed all five affected devices in each row. GPU power and FTDI wiring must not be inferred from row position.

The user explicitly authorized taking over the Jenkins devices for this audit. Active test processes on NUT009/010 were stopped. No kernels or firmware were flashed, and the rack PC was not rebooted.

Raw before/after supply, PCIe, USB identity and boot-ID evidence is retained on the rack PC in `~/rack-mapping-validation/mapping-result.json` and `NUT*.jsonl`. This audit proves the observed wiring and recovery of these individual actions, not long-term model recovery or crank-transient behavior.

After deployment, all ten named GPU power controls and all ten named FTDI
controls were checked again through `/opt/testing-rack/actions.py`; each
operated only the named GPU. Both strips returned intermittent network errors
during this pass; failed actions were retained in the audit logs and the
remaining checks resumed after connectivity recovered.

A later final-health check found NUT007's GPU absent with a USB link-enable
error in the kernel log. One normal FTDI reset recovered SuperSpeed enumeration
without rebooting the comma device. This recovery does not establish the cause
of that USB failure.

The rack-only keep-awake guard was installed and verified on all ten devices.
With `DisablePowerDown` temporarily removed, both normal power-off requests and
direct starts of `poweroff.target` were rejected; boot IDs stayed unchanged.
The parameter was restored. See [deployment](deployment.md#keep-rack-devices-powered).
