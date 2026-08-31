import json
import tempfile
from pathlib import Path

from hypothesis import HealthCheck, settings
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, rule
from hypothesis.strategies import integers

from app import ALLOWED_DURATIONS, Config, RackError, StateStore


class Clock:
    def __init__(self):
        self.value = 1_700_000_000.0

    def __call__(self):
        return self.value


class ReservationMachine(RuleBasedStateMachine):
    leases = Bundle("leases")

    def __init__(self):
        super().__init__()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        config_path = root / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "gateway_host": "gateway.invalid",
                    "gateway_port": 22,
                    "default_lease_minutes": 60,
                    "max_lease_minutes": 1440,
                    "max_devices_per_reservation": 8,
                    "devices": [
                        {
                            "name": f"NUT{i:03d}",
                            "device_type": "four",
                            "serial": f"{i:08x}",
                            "ftdi_serial": f"FTDI{i:04d}",
                        }
                        for i in range(1, 9)
                    ],
                }
            )
        )
        self.config = Config.load(config_path)
        self.state = root / "state.json"
        self.secret = root / "secret"
        StateStore.initialize(self.state, self.secret)
        self.clock = Clock()
        self.store = StateStore(self.config, self.state, self.secret, self.clock)
        self.model: dict[str, dict] = {}
        self.keys: dict[str, str] = {}

    def teardown(self):
        self.tmp.cleanup()

    def expire_model(self):
        expired = [
            cap
            for cap, lease in self.model.items()
            if lease["expires"] <= self.clock.value
        ]
        for cap in expired:
            self.keys.pop(self.model[cap]["key"], None)
            self.model.pop(cap)

    @rule(
        target=leases,
        user=integers(0, 5),
        count=integers(1, 8),
        duration=integers(0, 4),
        key_index=integers(0, 9),
    )
    def reserve(self, user, count, duration, key_index):
        self.expire_model()
        name = f"user-{user}"
        minutes = ALLOWED_DURATIONS[duration]
        key = f"model-request-key-{key_index:03d}"
        request = (name, count, minutes)
        expected_error = None
        if key in self.keys:
            lease = self.model[self.keys[key]]
            if lease["request"] != request:
                expected_error = "idempotency_conflict"
        elif any(x["name"].casefold() == name.casefold() for x in self.model.values()):
            expected_error = "reservation_exists"
        else:
            occupied = {
                device for lease in self.model.values() for device in lease["devices"]
            }
            if 8 - len(occupied) < count:
                expected_error = "insufficient_devices"
        try:
            result = self.store.reserve(name, count, minutes, key)
        except RackError as exc:
            assert exc.code == expected_error, (
                exc.code,
                expected_error,
                request,
                key,
                self.model,
            )
            return "error"
        assert expected_error is None
        if key in self.keys:
            assert result["capability"] == self.keys[key]
            return result["capability"]
        assert len(result["devices"]) == count
        self.model[result["capability"]] = {
            "name": name,
            "devices": result["devices"],
            "expires": self.clock.value + minutes * 60,
            "key": key,
            "request": request,
        }
        self.keys[key] = result["capability"]
        return result["capability"]

    @rule(capability=leases)
    def release(self, capability):
        self.expire_model()
        try:
            result = self.store.release(capability)
        except RackError as exc:
            assert capability not in self.model and exc.code == "invalid_capability"
            return
        lease = self.model.pop(capability)
        self.keys.pop(lease["key"], None)
        assert result["released"] == lease["devices"]

    @rule(minutes=integers(0, 1500))
    def advance(self, minutes):
        self.clock.value += minutes * 60
        self.expire_model()
        self.store.public_state()

    @rule()
    def restart(self):
        self.expire_model()
        self.store = StateStore(self.config, self.state, self.secret, self.clock)

    @invariant()
    def ownership_matches_model(self):
        self.expire_model()
        public = self.store.public_state()
        expected = {
            device: lease["name"]
            for lease in self.model.values()
            for device in lease["devices"]
        }
        actual = {
            device["name"]: device["nickname"]
            for device in public["devices"]
            if device["state"] == "reserved"
        }
        assert actual == expected
        assigned = [
            device for lease in self.model.values() for device in lease["devices"]
        ]
        assert len(assigned) == len(set(assigned))
        assert len(self.store.state["leases"]) == len(self.model)
        assert set(self.store.state["idempotency"]) == set(self.keys)


TestReservationMachine = ReservationMachine.TestCase
TestReservationMachine.settings = settings(
    max_examples=100,
    stateful_step_count=75,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
