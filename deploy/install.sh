#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
config=${CONFIG:-$root/config.json}
device_key=${DEVICE_KEY:-}
client_key=${CLIENT_PUBLIC_KEY:-}
known_hosts=${KNOWN_HOSTS:-}

if ! getent group testing-rack >/dev/null
then
  groupadd --system testing-rack
fi
if ! id testing-rack >/dev/null 2>&1
then
  useradd --system --gid testing-rack --home-dir /nonexistent --shell /usr/sbin/nologin testing-rack
fi
if ! id rack >/dev/null 2>&1
then
  useradd --system --gid testing-rack --home-dir /var/lib/testing-rack-gateway --create-home --shell /bin/bash rack
fi
passwd -d rack >/dev/null

install -d -o root -g root -m 0755 /opt/testing-rack /opt/testing-rack/web
install -d -o root -g root -m 0755 /etc/testing-rack
install -d -o testing-rack -g testing-rack -m 0750 /var/lib/testing-rack
install -d -o rack -g testing-rack -m 0750 /var/lib/testing-rack-gateway
install -d -o rack -g testing-rack -m 0700 /var/lib/testing-rack-gateway/.ssh
install -d -o rack -g testing-rack -m 0700 /var/lib/testing-rack-gateway/connections

install -o root -g root -m 0755 "$root/app.py" "$root/gateway.py" "$root/warm.py" "$root/actions.py" /opt/testing-rack/
install -o root -g root -m 0644 "$root/web/index.html" "$root/web/app.js" "$root/web/common.css" "$root/web/style.css" /opt/testing-rack/web/
install -o root -g root -m 0644 "$config" /etc/testing-rack/config.json

if [[ -n "$device_key" ]]
then
  install -o root -g testing-rack -m 0640 "$device_key" /etc/testing-rack/device_key
fi
if [[ ! -s /etc/testing-rack/device_key ]]
then
  echo "Set DEVICE_KEY for the gateway-only comma SSH key." >&2
  exit 1
fi
if [[ -n "$client_key" ]]
then
  install -o rack -g testing-rack -m 0600 "$client_key" /var/lib/testing-rack-gateway/.ssh/authorized_keys
fi
if [[ ! -s /var/lib/testing-rack-gateway/.ssh/authorized_keys ]]
then
  echo "Set CLIENT_PUBLIC_KEY for the company client key." >&2
  exit 1
fi
if [[ -n "$known_hosts" ]]
then
  install -o rack -g testing-rack -m 0600 "$known_hosts" /var/lib/testing-rack-gateway/.ssh/known_hosts
fi
if [[ ! -s /var/lib/testing-rack-gateway/.ssh/known_hosts ]]
then
  echo "Set KNOWN_HOSTS to the verified comma host-key file." >&2
  exit 1
fi

if [[ ! -e /var/lib/testing-rack/state.json ]]
then
  runuser -u testing-rack -- /usr/bin/python3 /opt/testing-rack/app.py init --config /etc/testing-rack/config.json --state /var/lib/testing-rack/state.json --secret /var/lib/testing-rack/secret.key
fi

install -o root -g root -m 0644 "$root/deploy/testing-rack.service" /etc/systemd/system/testing-rack.service
install -o root -g root -m 0644 "$root/deploy/testing-rack-connections.service" /etc/systemd/system/testing-rack-connections.service
install -o root -g root -m 0644 "$root/deploy/99-testing-rack.conf" /etc/ssh/sshd_config.d/99-testing-rack.conf
if grep -q '"gpu_power_switch"\|"ftdi_serial"' /etc/testing-rack/config.json
then
  install -o root -g root -m 0440 "$root/deploy/99-testing-rack-sudo" /etc/sudoers.d/testing-rack
  visudo -cf /etc/sudoers.d/testing-rack >/dev/null
fi
sshd -t
systemctl daemon-reload
systemctl enable --now testing-rack testing-rack-connections
systemctl restart testing-rack testing-rack-connections
systemctl reload ssh
for _attempt in {1..50}
do
  if curl --fail --silent http://localhost/healthz >/dev/null
  then
    echo "testing-rack is ready"
    exit 0
  fi
  sleep 0.1
done
echo "testing-rack did not become ready" >&2
exit 1
