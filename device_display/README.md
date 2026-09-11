# Rack idle background

The screen is the AGNOS display broker's background, not another display client.
It shows the position-based NUT name, physical row/position, reservation owner,
comma serial, power outlet, and GPU link speed with green/orange Chestnut icons
(gray disconnected text when absent). The physical mapping is in `inventory.json`;
hardware serials are the stable identity used to match reservations.

`launch.py` reads the installed `/usr/comma/magic.py` and applies a hash-checked,
in-memory adjustment to its idle loop. The installed AGNOS file is untouched.
The broker accepts clients before attempting an idle redraw and performs no
rack drawing while a client is connected. Descriptor handoff and updater
handling remain the installed AGNOS implementation. After rendering an idle frame,
the broker calls AGNOS's existing `power_screen()` just as its stock background
does, so a departing client's sleeping screen can wake. No openpilot processes,
setup flags, launch scripts, or device firmware are changed.

The idle screen uses a neutral black background and the stock AGNOS idle
brightness (65%, or 165/255 on this rack). It does not apply gamma or contrast
overrides. Openpilot retains control while its display client is connected.

The installer also adds a panel-type condition to AGNOS's `screen_calibration`
service. Its DWO register calibration must not run on the MICI Bantian panel.
The condition uses the live device-tree panel node; original calibration files
are preserved, and other panel types retain the stock service behavior.

The device bundle lives in `/data/rack-display/` and uses AGNOS's Python/raylib
plus a bundled font and the Chestnut icons. There is no openpilot checkout or Python-path dependency.
While idle, USB status is sampled every two seconds and reservations every
15 seconds; frames are redrawn only when their contents change. Network work
runs in a daemon thread and never blocks the display handoff thread. Active
clients suspend further reservation polling and USB sampling; a request already
in progress can finish. Rendering still consumes some resources.

On the rack PC, `rack-reservations.service` exposes a read-only serial-keyed
cache at port 8766. It reads `/etc/testing-rack/config.json` and the existing
public `/api/state`, without altering reservations or restarting the rack
service. Source data older than 30 seconds is marked stale; devices retain
their last successful observation for at most 45 seconds and otherwise show
`Reservation unknown`, never a fabricated `Available` status.

## Installation and activation

Use `deploy_from_rack.py` on the rack PC with explicit NUT names. It uses the
rack's existing device/setup SSH credentials; it does not copy credentials.
The installer verifies the serial and stock broker version, copies the bundle,
and installs `/etc/systemd/system/magic.service.d/90-rack-display.conf`.
Rootfs is returned to its prior read-only mount state after writing the drop-in.

If openpilot or a display client is present, installation **does not restart
magic**. Activation waits for its next normal start or a device reboot. Stopping
openpilot alone does not activate an already running stock broker. Once the
integration has activated, ordinary client exits automatically restore the rack
screen. Do not restart magic under an active client to force initial activation.

If no client or manager is present, the installer checks again before restarting
magic. It does not stop tests or reboot anything.

Reservations are associated by serial. The repository and deployed rack inventory
use the same physical-position numbering as the screens: NUT001–NUT005 on top,
NUT006–NUT010 on the bottom. Fixed reservations are defined in the rack configuration and matched by serial;
see the [dated assignment audit](../docs/rack-assignment-audit.md).

## Failure behavior and rollback

- Unknown AGNOS broker hash, missing configuration, or mismatched serial: run
  the stock broker. A rendering error disables the custom background and uses
  the original logo. Display clients continue through the stock handoff code.
- No network: retain the last observation briefly, then show reservation unknown.
- No openpilot checkout: continue using the AGNOS runtime and bundled font.
- Same-image reboot: the systemd drop-in starts the integration automatically.
- AGNOS image replacement/factory reset can remove the drop-in or `/data`; this
  is not guaranteed to survive flashing. Revalidate and reinstall for a new
  AGNOS version. Never bypass the broker version check.

To roll back, remove the magic service drop-in, run `systemctl daemon-reload`,
and let magic restart normally when safe. Stop/disable `rack-reservations` on
the rack PC if no devices need it. The original AGNOS broker is not modified.

## Verification

`python3 -m unittest discover -s device_display -p 'test_*.py' -v`

Tests cover the transformed broker loop's client priority and idle restoration,
unknown-version refusal, stale/missing reservations, and USB speed/disconnect
states. Run them as part of `./tests.sh` from the repository root or with the
focused command above. Live activation checks must respect the client-safety
rules in the installation section.
