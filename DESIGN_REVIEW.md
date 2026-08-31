# Design review

This review anticipates likely feedback from engineers, QA, security, and lab
operators. The key decision is whether the rack needs enforced exclusivity or
only a visible social reservation.

## The question the team must answer

What happens if two agents use the same device?

- If the cost is a failed test that is easy to retry, a trust-based dashboard
  may be enough.
- If it can corrupt state, interrupt flashing, damage hardware, or invalidate
  results, access must be enforced at the network boundary.

The current system sits between these models. It brokers access, but direct
`comma@comma-SERIAL.comma.internal` connectivity still exists. Until clients
are blocked from that path, the reservation is not a security boundary.
Hiding the serial in the UI does not change this.

## Option A: trust-based dashboard

Show free, reserved, offline, owner, and release. After reserving, expose the
real device command:

```text
ssh comma@comma-557d5c3a.comma.internal
```

Advantages:

- Lowest implementation and operational complexity
- Native SSH behavior, SCP, SFTP, forwarding, TTY, and tooling work unchanged
- No gateway latency or gateway single point of failure
- Easy for coding agents to understand

Drawbacks:

- Reservations are advisory
- A stale script or careless agent can use a reserved device
- Revocation is impossible without changing device or network credentials
- Name is not an authenticated identity

This is a valid design if the team explicitly accepts cooperative access. It
may be the best first version for a small trusted QA group.

## Option B: enforced gateway

Keep the reservation UI and gateway, then firewall direct device SSH so only
the rack PC can reach devices. This is the smallest design that makes the
current exclusivity claim true.

Advantages:

- Reservation and access use the same authority
- Tokens expire and can be revoked
- Device serials and credentials stay behind the gateway
- Optional power and FTDI actions remain scoped to a reservation

Drawbacks:

- Double SSH adds latency and quoting edge cases
- SCP, SFTP, port forwarding, agents, and unusual SSH features need explicit
  support and testing
- The rack PC, reservation service, DNS, state file, and gateway key become a
  shared failure domain
- A token copied into logs or screenshots grants the whole reservation

If enforcement is required, this is still the recommended near-term design.
Do not add more gateway features until users demonstrate a need for them.

## Option C: identity-aware access platform

Use company identity through Tailscale SSH, Teleport, or Boundary, then connect
reservation ownership to that identity. Tailscale SSH manages authentication,
host keys, access rules, revocation, SCP, and SFTP. Boundary can inject SSH
credentials without exposing them to users. Teleport adds identity and session
recording.

Advantages:

- Real user identity instead of a typed Name
- Central revocation and policy
- Mature SSH protocol handling
- Better audit and compliance options

Drawbacks:

- Considerably more operational and policy complexity
- Dynamic per-device reservation policy may still require custom integration
- Every device or an access worker needs compatible network placement
- It is likely excessive for ten devices and twenty trusted users

References:

- [Tailscale SSH](https://tailscale.com/docs/features/tailscale-ssh)
- [Boundary SSH targets](https://developer.hashicorp.com/boundary/docs/targets/create/ssh)
- [Teleport session recording](https://goteleport.com/docs/reference/architecture/session-recording/)

## Option D: labgrid as the backend

labgrid already models a coordinator, exporters, mutually exclusive places,
serial resources, power resources, health changes, and remote access. Resource
traffic goes directly to the exporter instead of through the coordinator. This
is a proven architecture for boards with attached power and serial resources.

Advantages:

- Avoids maintaining custom resource and locking semantics
- Designed for USB serial, power, bootstrap, fastboot, and remote labs
- Scales conceptually to multiple racks and exporters

Drawbacks:

- Its place, resource, exporter, and client model is more complex than this UI
- It does not automatically produce the zero-setup SSH experience requested
- A thin custom UI and identity integration would still be needed

Reference: [labgrid remote resources and places](https://github.com/labgrid-project/labgrid/blob/master/doc/overview.rst)

LAVA is more suitable when the primary unit is a scheduled declarative test
job. Its YAML job model is heavier than interactive agent access. [LAVA job documentation](https://lava.ciplatform.org/static/docs/technical-references/job-definition/job.html)

## Likely feedback on the current user experience

### The token command is unfamiliar

Current:

```text
ssh rack@chestnut 7Km3P9xQvT2w-NUT004
```

It is short, but the joined token and device look proprietary. A clearer form
would be:

```text
ssh rack@chestnut 7Km3P9xQvT2w NUT004
```

This is one character longer but makes the credential and target visibly
separate. It also makes appending a remote command easier to explain:

```text
ssh rack@chestnut 7Km3P9xQvT2w NUT004 'uname -a'
```

The current joined form remains acceptable if command length is the overriding
goal. Do not introduce a custom client merely to save a few characters.

### Copying many commands is noisy

One command per device is explicit and agent-friendly, but ten lines look
heavy. Reasonable alternatives are:

1. Keep one command per device. This is clearest and requires no setup.
2. Copy a compact table with `NUTxxx` and its command. This improves human
   scanning but adds text for agents.
3. Connect once to a reservation shell and select a device. This is shorter but
   creates interaction and is worse for coding agents.
4. Provide a custom `rack` CLI. This can become `rack ssh NUT004`, but violates
   the no-setup requirement and creates another client to distribute.

The current one-command-per-device output is the best match for zero setup.

### Ten-minute idle expiry may be too aggressive

An agent can spend more than ten minutes compiling or reasoning locally with no
SSH session. Its devices would then be released while it still assumes it owns
them. Active SSH heartbeats protect long remote commands but not gaps between
commands.

Likely requests will be:

- Increase idle timeout to 30 or 60 minutes
- Show the exact idle deadline prominently
- Add a cheap lease heartbeat API for coding agents
- Warn shortly before release

Adding automatic browser heartbeats would defeat inactivity cleanup because an
abandoned tab can stay open indefinitely. If a heartbeat is added, it should
come from the active agent process, not the passive web page.

### Name is not identity

Anyone can type another person's name. The one-reservation-per-name rule is
collision prevention, not authentication. Coworkers may prefer one of these:

- Accept this and label it clearly as cooperative
- Derive identity from an existing company reverse proxy
- Use Tailscale identity for the web and SSH layers

Do not build a new user database for this tool.

### Reservation recovery is browser-local

The token is stored in local storage. A different browser profile or computer
cannot recover the reservation by Name. Clearing browser storage also loses the
release control. This is the unavoidable result of having no accounts.

Possible responses:

- Accept it and rely on the short idle timeout
- Let users copy a private reservation link
- Add company identity and list reservations owned by that identity

Searching by Name and exposing release controls would let users steal each
other's reservations, so it should not be added without authentication.

### Tokens leak easily

Tokens appear in commands, terminal history, CI logs, screenshots, and agent
transcripts. One token currently grants every device in the reservation.

Low-complexity mitigations:

- Keep expiry short
- Make release immediate
- Avoid persistent server logs containing commands
- Consider a separate token per device only if leakage becomes a real problem

Per-device tokens improve blast radius but make copy and recovery more complex.
Do not add them preemptively.

### The web status can overpromise health

The current readiness signal comes from rack-side SSH connection health. It
does not prove the device application, storage, USB path, FTDI path, or power
outlet is healthy. Coworkers may interpret `READY` as a complete health check.

Rename or document the state as SSH reachable unless deeper probes are added.
Avoid expensive active probes from every browser poll.

### The Tailscale demo URL is not production architecture

The current Tailscale Serve endpoint runs on a workstation and proxies the rack
site. It disappears when that workstation is offline. It is suitable for a
review demo, not as the durable rack URL. A permanent private endpoint belongs
on the rack PC or a maintained internal proxy.

### The gateway is a single point of failure

If the rack PC fails, reservations, power control, FTDI control, health, and
device access all fail together. For a ten-device prototype this is reasonable.
At 100 devices, coworkers may ask for:

- One exporter or gateway per physical rack
- A coordinator that can fail without killing established sessions
- Backups and explicit recovery for reservation state
- Metrics for connection latency, errors, and lease expiry

labgrid uses coordinator plus exporter separation for this reason. Do not build
that split until a second rack exists.

### Heartbeat writes may not scale cleanly

Each active gateway process refreshes persistent reservation state once per
minute. With many simultaneous sessions this adds lock contention and fsync
traffic. It is fine for the current rack. Before 100 devices, coalesce updates
per lease or keep recent heartbeat state in memory with periodic persistence.

### Device actions need a stable contract

`gpu_power:on`, `gpu_power:off`, and `ftdi:reset` are simple and discoverable.
The likely concern is growth into an unstructured command plugin system. Keep a
small configured allowlist of named actions. Do not accept arbitrary local
commands from configuration.

## Serial console alternatives

ser2net is mature for exporting serial ports, and modern gensio stacks can add
TLS and authentication. It is useful for FTDI console access, but it does not
solve device SSH reservation by itself. Direct TCP serial ports also create a
new client command and a port allocation scheme. [ser2net project](https://github.com/cminyard/ser2net)

## Recommended discussion position

1. Ask the team whether exclusivity must be enforced or merely communicated.
2. If cooperative access is acceptable, simplify to the dashboard plus direct
   serial hostnames and remove the SSH gateway.
3. If enforcement is required, keep the current gateway and add the network ACL
   that blocks direct device SSH. Without that ACL, do not describe it as secure.
4. Keep the UI, exact matrix selection, API, power actions, and FTDI actions.
5. Reconsider the 10-minute idle timeout after observing real agent workflows.
6. Do not add accounts, a custom CLI, session recording, or a distributed
   coordinator until actual usage demonstrates the need.

The simplest honest design is better than a partially enforced sophisticated
one. The prototype is useful today, but the team must explicitly choose trust
or enforcement before calling the access boundary complete.
