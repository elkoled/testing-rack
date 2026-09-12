# Deployment

Run one reservation-service process per state file. The state lock protects
threads within that process; multiple processes must not share the file.

## Configuration

`config.json` holds the rack identity, gateway address, limits, and device
inventory. Device names are `NUT` followed by digits; serials are eight lowercase
hexadecimal characters and must be unique.

Optional device fields:

- `reserved_by`: fixed owner, visible but excluded from API allocation.
- `ftdi_serial`: unique FTDI adapter serial for reset actions.
- `gpu_power_switch`: named GPU outlet; enables power actions.

The display's physical row and position live in
[`device_display/inventory.json`](../device_display/inventory.json). Device
names, serials, and outlets must agree with the rack configuration. USB port
order is not physical rack position.

## Install or upgrade

On the rack PC, use a reviewed checkout and the existing verified inventory.
Python 3.12, OpenSSH server/client, systemd, curl, and sudo are required.
For a first install, provide the device private key and a verified device host-key
file:

```sh
sudo env DEVICE_KEY=/path/to/device_key KNOWN_HOSTS=/path/to/known_hosts ./deploy/install.sh
```

For subsequent upgrades, the installer reuses installed credentials:

```sh
sudo ./deploy/install.sh
```

`CONFIG=/path/to/config.json` selects a different source inventory. The installer
copies it into `/etc/testing-rack/config.json`; compare it with the installed
inventory before upgrading. It replaces `/opt/testing-rack`, restarts both rack
services, and reloads SSH. Schedule upgrades around active work because restarting
private SSH connections can interrupt sessions. State and the secret are retained.

Hardware actions currently depend on the rack PC's `batman` account and external
helpers at the paths declared in [`actions.py`](../actions.py). The power helper
maps device serials to outlets; verify that mapping agrees with `gpu_power_switch`.

## Services and state

| Location | Purpose |
| --- | --- |
| `/opt/testing-rack` | Installed application and static assets |
| `/etc/testing-rack` | Inventory and device key |
| `/var/lib/testing-rack` | Reservation state and token derivation secret |
| `/var/lib/testing-rack-gateway` | Verified host keys, private SSH sockets, health |
| `testing-rack.service` | HTTP service on port 80 |
| `testing-rack-connections.service` | Persistent device SSH connections |

The gateway's `rack` account uses a forced command. Its SSH configuration allows
keyless authentication to reach that command; reservation-token validation gates
device access. The account does not offer a gateway shell or port forwarding.

```sh
systemctl status testing-rack testing-rack-connections
journalctl -u testing-rack -u testing-rack-connections --since '10 minutes ago'
curl --fail http://localhost/healthz
curl --fail http://localhost/api/state
```

`/healthz` checks HTTP service liveness. Device `ready` means connection health,
not that a device is suitable for a particular test. A corrupt state file fails
closed: the service does not automatically recover the previous snapshot because
that could allocate an already-reserved device twice. Preserve the state and
secret together when making backups.

The optional screen integration has its own
[installation and rollback instructions](../device_display/README.md).

## Keep rack devices powered

After installing a device's rack-display identity, run `deploy/keep-awake.sh`
as root on that device. It persistently masks `power_monitor.service` and
`poweroff.target` in `/etc/systemd/system`, outside openpilot and Params. Normal
software power-off requests are rejected even if CI clears `DisablePowerDown`.
Reboot remains available. The installer restores the root filesystem's original
mount mode and leaves `/data/continue.sh` unchanged.

Verify `systemctl is-enabled power_monitor.service poweroff.target` reports
`masked`. Keep `DisablePowerDown` enabled too, so openpilot does not initiate its
shutdown sequence. Reapply the guard after replacing the AGNOS image. Before
repurposing a device outside the rack, remove these masks deliberately.
