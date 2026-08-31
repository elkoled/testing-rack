#!/usr/bin/env python3
"""Small, single-writer testing rack reservation service."""

from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


NAME_RE = re.compile(r"NUT([0-9]+)$")
SERIAL_RE = re.compile(r"[0-9a-f]{8}$")
FTDI_SERIAL_RE = re.compile(r"[A-Z0-9]{8}$")
IDEMPOTENCY_RE = re.compile(r"[A-Za-z0-9_-]{16,128}$")
BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
CAPABILITY_RE = re.compile(
    r"(?:[1-9A-HJ-NP-Za-km-z]{12}|[0123456789ABCDEFGHJKMNPQRSTVWXYZ]{16}|[A-Za-z0-9_-]{22})$"
)
ALLOWED_DURATIONS = (60, 180, 360, 720, 1440)
MAX_BODY = 8192


class RackError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


@dataclass(frozen=True)
class Config:
    display_name: str
    gateway_host: str
    gateway_port: int
    default_lease_minutes: int
    max_lease_minutes: int
    max_devices_per_reservation: int
    devices: tuple[dict[str, str], ...]

    @classmethod
    def load(cls, path: Path) -> "Config":
        try:
            raw = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot load config: {exc}") from exc
        required = {
            "gateway_host",
            "gateway_port",
            "default_lease_minutes",
            "max_lease_minutes",
            "max_devices_per_reservation",
            "devices",
        }
        if not required.issubset(raw) or not set(raw).issubset(
            required | {"display_name"}
        ):
            raise ValueError("config fields are invalid")
        display_name = raw.get("display_name", "testing-rack")
        if not isinstance(display_name, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{0,31}", display_name
        ):
            raise ValueError("display_name is invalid")
        if not isinstance(raw["gateway_host"], str) or not raw["gateway_host"].strip():
            raise ValueError("gateway_host must be a non-empty string")
        if (
            isinstance(raw["gateway_port"], bool)
            or not isinstance(raw["gateway_port"], int)
            or not 1 <= raw["gateway_port"] <= 65535
        ):
            raise ValueError("gateway_port must be a valid TCP port")
        for key in (
            "default_lease_minutes",
            "max_lease_minutes",
            "max_devices_per_reservation",
        ):
            if (
                isinstance(raw[key], bool)
                or not isinstance(raw[key], int)
                or raw[key] < 1
            ):
                raise ValueError(f"{key} must be a positive integer")
        if raw["default_lease_minutes"] not in ALLOWED_DURATIONS or raw[
            "max_lease_minutes"
        ] > max(ALLOWED_DURATIONS):
            raise ValueError("lease limits must use supported durations")
        if not isinstance(raw["devices"], list) or not raw["devices"]:
            raise ValueError("devices must be a non-empty list")
        names, serials, ftdi_serials, gpu_power_switches, devices = (
            set(),
            set(),
            set(),
            set(),
            [],
        )
        for item in raw["devices"]:
            required_fields = {"name", "device_type", "serial"}
            optional_fields = {"ftdi_serial", "gpu_power_switch"}
            if (
                not isinstance(item, dict)
                or not required_fields.issubset(item)
                or not set(item).issubset(required_fields | optional_fields)
            ):
                raise ValueError("every device needs name, device_type, and serial")
            if not NAME_RE.fullmatch(item["name"]):
                raise ValueError(f"invalid device name: {item['name']!r}")
            for key in item:
                if not isinstance(item[key], str) or not item[key].strip():
                    raise ValueError(f"{item['name']} has an invalid {key}")
            if not SERIAL_RE.fullmatch(item["serial"]):
                raise ValueError(f"{item['name']} has an invalid serial")
            if "ftdi_serial" in item and not FTDI_SERIAL_RE.fullmatch(
                item["ftdi_serial"]
            ):
                raise ValueError(f"{item['name']} has an invalid ftdi_serial")
            if "gpu_power_switch" in item and not re.fullmatch(
                r"[a-z0-9][a-z0-9_-]{0,31}", item["gpu_power_switch"]
            ):
                raise ValueError(f"{item['name']} has an invalid gpu_power_switch")
            for value, seen, label in (
                (item["name"], names, "name"),
                (item["serial"], serials, "serial"),
                (item.get("ftdi_serial"), ftdi_serials, "ftdi_serial"),
                (
                    item.get("gpu_power_switch"),
                    gpu_power_switches,
                    "gpu_power_switch",
                ),
            ):
                if value is None:
                    continue
                if value in seen:
                    raise ValueError(f"duplicate {label}: {value}")
                seen.add(value)
            devices.append(dict(item))
        if raw["max_devices_per_reservation"] > len(devices):
            raise ValueError("max_devices_per_reservation exceeds inventory")
        return cls(
            display_name,
            raw["gateway_host"],
            raw["gateway_port"],
            raw["default_lease_minutes"],
            raw["max_lease_minutes"],
            raw["max_devices_per_reservation"],
            tuple(devices),
        )


class StateStore:
    def __init__(
        self,
        config: Config,
        state_path: Path,
        secret_path: Path,
        now=time.time,
        health_path: Path | None = None,
    ):
        self.config, self.path, self.previous = (
            config,
            state_path,
            state_path.with_name("state.previous.json"),
        )
        self.now, self.lock, self.health_path = now, threading.RLock(), health_path
        self.secret = secret_path.read_bytes()
        if len(self.secret) < 32:
            raise ValueError("secret must contain at least 32 random bytes")
        self.state = self._load_state()
        with self.lock:
            self._expire_and_persist_if_needed()

    @staticmethod
    def initialize(state_path: Path, secret_path: Path) -> None:
        if state_path.exists() or secret_path.exists():
            raise ValueError("state or secret already exists; refusing to overwrite")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "version": 1,
            "leases": [],
            "idempotency": {},
            "overrides": {},
            "metadata": {},
            "last_released": {},
        }
        _atomic_create(
            state_path,
            json.dumps(state, separators=(",", ":"), sort_keys=True).encode(),
            0o600,
        )
        _atomic_create(secret_path, secrets.token_bytes(32), 0o600)

    def _load_state(self) -> dict[str, Any]:
        try:
            state = json.loads(self.path.read_text())
            self._validate_state(state)
            return state
        except FileNotFoundError as exc:
            raise ValueError(
                "current state is missing; refusing stale recovery"
            ) from exc
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            # A present-but-invalid current file may have contained a reservation
            # already returned to a caller. Loading an older snapshot could free that
            # hardware twice, so corruption must fail closed.
            raise ValueError(
                f"current state is invalid; refusing stale recovery: {exc}"
            ) from exc

    def _validate_state(self, state: Any) -> None:
        if not isinstance(state, dict) or state.get("version") != 1:
            raise ValueError("unsupported state")
        if not isinstance(state.get("leases"), list) or not isinstance(
            state.get("idempotency"), dict
        ):
            raise ValueError("malformed state collections")
        configured = {d["name"] for d in self.config.devices}
        occupied = set()
        for lease in state["leases"]:
            required = {
                "display_id",
                "name",
                "devices",
                "expires_at",
                "capability_hash",
                "created_at",
                "idempotency_key",
            }
            if (
                not isinstance(lease, dict)
                or set(lease) != required
                or not set(lease["devices"]) <= configured
            ):
                raise ValueError("malformed lease")
            if occupied.intersection(lease["devices"]):
                raise ValueError("device appears in multiple leases")
            occupied.update(lease["devices"])
        for key in ("overrides", "metadata", "last_released"):
            if not isinstance(state.get(key), dict):
                raise ValueError(f"malformed {key}")

    def _capability(self, key: str) -> str:
        value = int.from_bytes(
            hmac.new(
                self.secret, ("capability:" + key).encode(), hashlib.sha256
            ).digest(),
            "big",
        ) % (58**12)
        result = ""
        for _ in range(12):
            value, digit = divmod(value, 58)
            result = BASE58[digit] + result
        return result

    @staticmethod
    def _hash_capability(capability: str) -> str:
        return hashlib.sha256(capability.encode()).hexdigest()

    def _find_lease(self, capability: str) -> dict[str, Any]:
        if not CAPABILITY_RE.fullmatch(capability):
            raise RackError(
                403,
                "invalid_capability",
                "Reservation capability is invalid or expired.",
            )
        digest = self._hash_capability(capability)
        lease = next(
            (
                x
                for x in self.state["leases"]
                if hmac.compare_digest(x["capability_hash"], digest)
            ),
            None,
        )
        if lease is None:
            raise RackError(
                403,
                "invalid_capability",
                "Reservation capability is invalid or expired.",
            )
        return lease

    def _connection_health(self) -> dict[str, str]:
        if self.health_path is None:
            return {}
        try:
            health = json.loads(self.health_path.read_text())
            if not isinstance(health, dict) or any(
                value not in {"ready", "offline"} for value in health.values()
            ):
                raise ValueError("invalid health")
            return health
        except (OSError, ValueError, json.JSONDecodeError):
            return {device["name"]: "unknown" for device in self.config.devices}

    def _effective_health(
        self, name: str, connection_health: dict[str, str] | None = None
    ) -> str:
        override = self.state["overrides"].get(name)
        if override in {"degraded", "offline", "unknown"}:
            return override
        connection_health = (
            self._connection_health()
            if connection_health is None
            else connection_health
        )
        if name in connection_health:
            return connection_health[name]
        return self.state["metadata"].get(name, {}).get("health", "ready")

    def _expire(self, state: dict[str, Any], now: float) -> bool:
        expired = [x for x in state["leases"] if x["expires_at"] <= now]
        if not expired:
            return False
        state["leases"] = [x for x in state["leases"] if x["expires_at"] > now]
        live_keys = {x["idempotency_key"] for x in state["leases"]}
        state["idempotency"] = {
            k: v for k, v in state["idempotency"].items() if k in live_keys
        }
        return True

    def _expire_and_persist_if_needed(self) -> None:
        candidate = copy.deepcopy(self.state)
        if self._expire(candidate, self.now()):
            self._persist(candidate)

    def _persist(self, candidate: dict[str, Any]) -> None:
        self._validate_state(candidate)
        payload = json.dumps(candidate, separators=(",", ":"), sort_keys=True).encode()
        tmp = self.path.with_name(f".{self.path.name}.{secrets.token_hex(8)}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if self.path.exists():
                backup_tmp = self.previous.with_name(
                    f".{self.previous.name}.{secrets.token_hex(8)}.tmp"
                )
                backup_fd = os.open(
                    backup_tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
                try:
                    with os.fdopen(backup_fd, "wb") as backup:
                        backup.write(self.path.read_bytes())
                        backup.flush()
                        os.fsync(backup.fileno())
                    os.replace(backup_tmp, self.previous)
                finally:
                    try:
                        backup_tmp.unlink()
                    except FileNotFoundError:
                        pass
            os.replace(tmp, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
        self.state = candidate

    def public_state(self) -> dict[str, Any]:
        with self.lock:
            self._expire_and_persist_if_needed()
            now = self.now()
            owners = {
                name: lease
                for lease in self.state["leases"]
                for name in lease["devices"]
            }
            connection_health = self._connection_health()
            devices = []
            for item in sorted(
                self.config.devices,
                key=lambda d: int(NAME_RE.fullmatch(d["name"]).group(1)),
            ):
                lease, health = (
                    owners.get(item["name"]),
                    self._effective_health(item["name"], connection_health),
                )
                devices.append(
                    {
                        "name": item["name"],
                        "device_type": item["device_type"],
                        "health": health,
                        "state": "reserved" if lease else health,
                        "owner": lease["name"] if lease else None,
                        "expires_at": lease["expires_at"] if lease else None,
                    }
                )
            return {
                "now": now,
                "devices": devices,
                "durations": [
                    x for x in ALLOWED_DURATIONS if x <= self.config.max_lease_minutes
                ],
                "max_devices": self.config.max_devices_per_reservation,
                "default_duration": self.config.default_lease_minutes,
            "gateway_host": self.config.gateway_host,
            "display_name": self.config.display_name,
            }

    def device(self, name: str) -> dict[str, Any]:
        state = self.public_state()
        device = next((x for x in state["devices"] if x["name"] == name), None)
        if device is None:
            raise RackError(404, "not_found", "Device does not exist.")
        meta = self.state["metadata"].get(name, {})
        return {
            **device,
            "metadata": meta,
        }

    def reserve(
        self, name: Any, count: Any, duration: Any, key: Any
    ) -> dict[str, Any]:
        name = _validate_name(name)
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 1 <= count <= self.config.max_devices_per_reservation
        ):
            raise RackError(
                400,
                "invalid_count",
                f"Device count must be 1–{self.config.max_devices_per_reservation}.",
            )
        if (
            isinstance(duration, bool)
            or duration not in ALLOWED_DURATIONS
            or duration > self.config.max_lease_minutes
        ):
            raise RackError(
                400, "invalid_duration", "Choose one of the offered durations."
            )
        if not isinstance(key, str) or not IDEMPOTENCY_RE.fullmatch(key):
            raise RackError(
                400, "invalid_idempotency_key", "Idempotency key is malformed."
            )
        with self.lock:
            self._expire_and_persist_if_needed()
            capability = self._capability(key)
            if key in self.state["idempotency"]:
                lease = next(
                    (
                        item
                        for item in self.state["leases"]
                        if item["idempotency_key"] == key
                    ),
                    None,
                )
                if lease is None:
                    raise RackError(
                        500,
                        "state_inconsistent",
                        "Reservation state is inconsistent; refusing allocation.",
                    )
                original_duration = round(
                    (lease["expires_at"] - lease["created_at"]) / 60
                )
                if (
                    lease["name"] != name
                    or len(lease["devices"]) != count
                    or original_duration != duration
                ):
                    raise RackError(
                        409,
                        "idempotency_conflict",
                        "That request identifier was already used for different reservation details.",
                    )
                return self._reservation_response(lease, capability)
            # With no account system, the normalized display name is the user identity.
            # Enforce this under the same lock as allocation so extra tabs and concurrent
            # requests cannot create a second live reservation for that identity.
            existing = next(
                (
                    lease
                    for lease in self.state["leases"]
                    if lease["name"].casefold() == name.casefold()
                ),
                None,
            )
            if existing is not None:
                raise RackError(
                    409,
                    "reservation_exists",
                    f"{existing['name']} already has reservation {existing['display_id']}. Release it before reserving again.",
                    display_id=existing["display_id"],
                    expires_at=existing["expires_at"],
                )
            occupied = {
                name for lease in self.state["leases"] for name in lease["devices"]
            }
            connection_health = self._connection_health()
            ready = [
                d["name"]
                for d in self.config.devices
                if d["name"] not in occupied
                and self._effective_health(d["name"], connection_health) == "ready"
            ]
            ready.sort(key=lambda name: int(NAME_RE.fullmatch(name).group(1)))
            if len(ready) < count:
                raise RackError(
                    409,
                    "insufficient_devices",
                    f"Only {len(ready)} devices are ready.",
                    available=len(ready),
                )
            now = self.now()
            lease = {
                "display_id": secrets.token_hex(2).upper(),
                "name": name,
                "devices": ready[:count],
                "expires_at": now + duration * 60,
                "capability_hash": self._hash_capability(capability),
                "created_at": now,
                "idempotency_key": key,
            }
            candidate = copy.deepcopy(self.state)
            candidate["leases"].append(lease)
            candidate["idempotency"][key] = lease["display_id"]
            self._persist(candidate)
            return self._reservation_response(lease, capability)

    def _reservation_response(
        self, lease: dict[str, Any], capability: str
    ) -> dict[str, Any]:
        destination = f"rack@{self.config.gateway_host}"
        prefix = (
            f"ssh {destination}"
            if self.config.gateway_port == 22
            else f"ssh -p{self.config.gateway_port} -oStrictHostKeyChecking=accept-new {destination}"
        )
        devices = sorted(
            lease["devices"], key=lambda name: int(NAME_RE.fullmatch(name).group(1))
        )
        commands = [f"{prefix} {capability}-{name}" for name in devices]
        actions = {}
        for name in devices:
            device = next(item for item in self.config.devices if item["name"] == name)
            available = []
            if "gpu_power_switch" in device:
                available.extend(("gpu_power:on", "gpu_power:off"))
            if "ftdi_serial" in device:
                available.append("ftdi:reset")
            actions[name] = available
        return {
            "capability": capability,
            "display_id": lease["display_id"],
            "name": lease["name"],
            "devices": devices,
            "expires_at": lease["expires_at"],
            "reservation_url": f"/#reservation={capability}",
            "gateway_command": commands[0],
            "access_commands": commands,
            "actions": actions,
        }

    def current(self, capability: str) -> dict[str, Any]:
        with self.lock:
            self._expire_and_persist_if_needed()
            return self._reservation_response(self._find_lease(capability), capability)

    def release(self, capability: str) -> dict[str, Any]:
        with self.lock:
            self._expire_and_persist_if_needed()
            lease = self._find_lease(capability)
            candidate = copy.deepcopy(self.state)
            candidate["leases"] = [
                x for x in candidate["leases"] if x["display_id"] != lease["display_id"]
            ]
            candidate["idempotency"].pop(lease["idempotency_key"], None)
            self._persist(candidate)
            return {
                "released": sorted(
                    lease["devices"],
                    key=lambda name: int(NAME_RE.fullmatch(name).group(1)),
                )
            }

    def resolve(self, capability: str, name: Any) -> dict[str, Any]:
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            raise RackError(400, "invalid_device", "Device name is malformed.")
        with self.lock:
            self._expire_and_persist_if_needed()
            lease = self._find_lease(capability)
            if name not in lease["devices"]:
                raise RackError(
                    403, "not_reserved", "That device is not part of this reservation."
                )
            device = next(d for d in self.config.devices if d["name"] == name)
            result = {
                "name": name,
                "serial": device["serial"],
                "health": self._effective_health(name),
                "expires_at": lease["expires_at"],
                "display_name": self.config.display_name,
            }
            for key in ("ftdi_serial", "gpu_power_switch"):
                if key in device:
                    result[key] = device[key]
            return result


def _validate_name(value: Any) -> str:
    if not isinstance(value, str):
        raise RackError(400, "invalid_name", "Name is required.")
    value = value.strip()
    if not 2 <= len(value) <= 32 or not value.isprintable():
        raise RackError(
            400, "invalid_name", "Name must be 2–32 printable characters."
        )
    return value


def _atomic_create(path: Path, data: bytes, mode: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class Handler(BaseHTTPRequestHandler):
    store: StateStore
    static_dir: Path
    common_static_dir: Path
    server_version = "testing-rack/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(
            json.dumps(
                {
                    "at": time.time(),
                    "remote": self.client_address[0],
                    "message": fmt % args,
                }
            )
        )

    def _headers(self, status: int, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        self.end_headers()

    def _json(self, status: int, value: Any) -> None:
        data = json.dumps(value, separators=(",", ":")).encode()
        self._headers(status, "application/json; charset=utf-8", len(data))
        self.wfile.write(data)

    def _error(self, exc: RackError) -> None:
        self._json(exc.status, {"error": exc.code, "message": exc.message, **exc.extra})

    def _capability(self) -> str:
        return self.headers.get("X-Testing-Rack-Capability", "")

    def _body(self) -> dict[str, Any]:
        if (
            self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            raise RackError(
                415, "unsupported_media_type", "Content-Type must be application/json."
            )
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isdigit():
            raise RackError(400, "invalid_body", "A JSON request body is required.")
        length = int(raw_length)
        if length > MAX_BODY:
            raise RackError(413, "body_too_large", "Request body is too large.")
        try:
            value = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            raise RackError(
                400, "invalid_json", "Request body is not valid JSON."
            ) from None
        if not isinstance(value, dict):
            raise RackError(400, "invalid_body", "Request body must be an object.")
        return value

    def do_GET(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == "/api/state":
                self._json(200, self.store.public_state())
            elif path == "/api/agent":
                self._json(
                    200,
                    {
                        "purpose": "Reserve exclusive test-device access.",
                        "reserve": {
                            "method": "POST",
                            "path": "/api/reservations",
                            "json": {
                                "name": "your name",
                                "count": 1,
                                "duration_minutes": 60,
                                "idempotency_key": "unique string of at least 16 characters",
                            },
                        },
                        "result": "Run a command from access_commands.",
                        "release": {
                            "method": "DELETE",
                            "path": "/api/reservations/current",
                            "header": "X-Testing-Rack-Capability: capability from reservation",
                        },
                    },
                )
            elif path.startswith("/api/devices/"):
                self._json(200, self.store.device(path.removeprefix("/api/devices/")))
            elif path == "/api/reservations/current":
                self._json(200, self.store.current(self._capability()))
            elif path == "/healthz":
                self._json(200, {"status": "ok"})
            elif path in ("/", "/index.html"):
                self._file("index.html", "text/html; charset=utf-8")
            elif path == "/app.js":
                self._file(
                    "app.js", "text/javascript; charset=utf-8", self.common_static_dir
                )
            elif path == "/style.css":
                self._file("style.css", "text/css; charset=utf-8")
            elif path == "/common.css":
                self._file(
                    "common.css", "text/css; charset=utf-8", self.common_static_dir
                )
            elif path == "/favicon.ico":
                self._headers(204, "image/x-icon", 0)
            else:
                raise RackError(404, "not_found", "Path does not exist.")
        except RackError as exc:
            self._error(exc)

    def do_POST(self) -> None:
        try:
            path, body = urlparse(self.path).path, self._body()
            if path == "/api/reservations":
                allowed = {"name", "count", "duration_minutes", "idempotency_key"}
                if set(body) != allowed:
                    raise RackError(
                        400, "invalid_fields", "Reservation fields are invalid."
                    )
                self._json(
                    201,
                    self.store.reserve(
                        body["name"],
                        body["count"],
                        body["duration_minutes"],
                        body["idempotency_key"],
                    ),
                )
            elif path == "/api/gateway/resolve":
                if set(body) != {"device"}:
                    raise RackError(
                        400, "invalid_fields", "Gateway fields are invalid."
                    )
                self._json(200, self.store.resolve(self._capability(), body["device"]))
            else:
                raise RackError(404, "not_found", "Path does not exist.")
        except RackError as exc:
            self._error(exc)

    def do_DELETE(self) -> None:
        try:
            if urlparse(self.path).path != "/api/reservations/current":
                raise RackError(404, "not_found", "Path does not exist.")
            self._json(200, self.store.release(self._capability()))
        except RackError as exc:
            self._error(exc)

    def _method_not_allowed(self, head: bool = False) -> None:
        data = json.dumps(
            {"error": "method_not_allowed", "message": "Method is not allowed."},
            separators=(",", ":"),
        ).encode()
        self.send_response(405)
        self.send_header("Allow", "GET, POST, DELETE")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", "0" if head else str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        if not head:
            self.wfile.write(data)

    def do_HEAD(self) -> None:
        self._method_not_allowed(True)

    def do_OPTIONS(self) -> None:
        self._method_not_allowed()

    def do_PUT(self) -> None:
        self._method_not_allowed()

    def do_PATCH(self) -> None:
        self._method_not_allowed()

    def _file(
        self, name: str, content_type: str, directory: Path | None = None
    ) -> None:
        data = ((directory or self.static_dir) / name).read_bytes()
        self._headers(200, content_type, len(data))
        self.wfile.write(data)


def main() -> None:
    root = Path(__file__).parent
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("init", "serve"))
    parser.add_argument("--config", type=Path, default=root / "config.json")
    parser.add_argument("--state", type=Path, default=root / "data/state.json")
    parser.add_argument("--secret", type=Path, default=root / "data/secret.key")
    parser.add_argument("--health", type=Path)
    parser.add_argument("--bind", default="localhost")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "init":
        Config.load(args.config)
        StateStore.initialize(args.state, args.secret)
        print(f"initialized {args.state}")
        return
    config = Config.load(args.config)
    store = StateStore(config, args.state, args.secret, health_path=args.health)
    static_dir = root / "web"
    handler = type(
        "TestingRackHandler",
        (Handler,),
        {"store": store, "static_dir": static_dir, "common_static_dir": static_dir},
    )
    server = ThreadingHTTPServer((args.bind, args.port), handler)
    print(f"testing-rack listening on http://{args.bind}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
