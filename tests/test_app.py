import json
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from pathlib import Path

from app import Config, RackError, StateStore

ROOT = Path(__file__).resolve().parent.parent


class Clock:
    def __init__(self):
        self.value = 1_700_000_000.0

    def __call__(self):
        return self.value


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        config_path = root / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "gateway_host": "gateway.invalid",
                    "gateway_port": 22022,
                    "default_lease_minutes": 60,
                    "max_lease_minutes": 1440,
                    "max_devices_per_reservation": 3,
                    "devices": [
                        {
                            "name": f"NUT{i:03d}",
                            "host": f"192.0.2.{i}",
                            "model": "test device",
                            "expected_ftdi_serial": f"FT{i}",
                        }
                        for i in range(1, 4)
                    ],
                }
            )
        )
        self.config = Config.load(config_path)
        self.state, self.secret = root / "state.json", root / "secret.key"
        StateStore.initialize(self.state, self.secret)
        self.clock = Clock()
        self.store = StateStore(self.config, self.state, self.secret, self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def reserve(self, count=1, key="abcdefghijklmnop"):
        return self.store.reserve("alex", count, 60, key)

    def test_atomic_multi_device_reservation(self):
        result = self.reserve(3)
        self.assertEqual(result["devices"], ["NUT001", "NUT002", "NUT003"])
        with self.assertRaises(RackError) as caught:
            self.store.reserve("mira", 1, 60, "different-key-123")
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(len(self.store.state["leases"]), 1)

    def test_idempotency_returns_same_capability_without_second_lease(self):
        first = self.reserve(2)
        second = self.reserve(2)
        self.assertEqual(first, second)
        self.assertEqual(len(self.store.state["leases"]), 1)

    def test_idempotency_key_rejects_different_request(self):
        self.reserve(1)
        for args in (("mira", 1, 60), ("alex", 2, 60), ("alex", 1, 180)):
            with self.subTest(args=args), self.assertRaises(RackError) as caught:
                self.store.reserve(*args, "abcdefghijklmnop")
            self.assertEqual(caught.exception.code, "idempotency_conflict")
        self.assertEqual(len(self.store.state["leases"]), 1)

    def test_one_live_reservation_per_name(self):
        first = self.reserve(1)
        with self.assertRaises(RackError) as caught:
            self.store.reserve(" ALEX ", 1, 60, "different-key-123")
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.code, "reservation_exists")
        self.assertEqual(caught.exception.extra["display_id"], first["display_id"])
        self.assertEqual(len(self.store.state["leases"]), 1)

    def test_same_name_concurrent_requests_have_one_winner(self):
        barrier = threading.Barrier(8)
        outcomes = []

        def contender(index):
            barrier.wait()
            try:
                self.store.reserve("alex", 1, 60, f"same-user-key-{index:03d}")
                outcomes.append("won")
            except RackError as exc:
                outcomes.append(exc.code)

        threads = [threading.Thread(target=contender, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(outcomes.count("won"), 1)
        self.assertEqual(outcomes.count("reservation_exists"), 7)

    def test_capability_scope_and_release(self):
        result = self.reserve(2)
        self.assertEqual(len(result["access_commands"]), 2)
        self.assertTrue(result["access_commands"][0].endswith("-NUT001"))
        self.assertTrue(result["access_commands"][1].endswith("-NUT002"))
        self.assertEqual(
            self.store.resolve(result["capability"], "NUT001")["host"], "192.0.2.1"
        )
        with self.assertRaises(RackError) as caught:
            self.store.resolve(result["capability"], "NUT003")
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(
            self.store.release(result["capability"])["released"], ["NUT001", "NUT002"]
        )
        with self.assertRaises(RackError):
            self.store.current(result["capability"])

    def test_access_argument_can_never_be_parsed_as_an_ssh_option(self):
        result = self.reserve(1)
        argument = result["access_commands"][0].split()[-1]
        self.assertTrue(argument.endswith("-NUT001"))
        self.assertFalse(argument.startswith("-"))
        self.assertRegex(argument, r"^[1-9A-HJ-NP-Za-km-z]{12}-NUT001$")

    def test_expiry_invalidates_capability_and_frees_devices(self):
        result = self.reserve(2)
        self.clock.value += 3600
        state = self.store.public_state()
        self.assertEqual(sum(d["state"] == "ready" for d in state["devices"]), 3)
        with self.assertRaises(RackError):
            self.store.resolve(result["capability"], "NUT001")

    def test_restart_preserves_active_reservation(self):
        result = self.reserve(2)
        restarted = StateStore(self.config, self.state, self.secret, self.clock)
        self.assertEqual(
            restarted.current(result["capability"])["devices"], result["devices"]
        )

    def test_failed_atomic_commit_never_changes_memory_or_current_disk_state(self):
        before_memory = json.loads(json.dumps(self.store.state))
        before_disk = self.state.read_bytes()
        real_replace = __import__("os").replace

        def fail_final_replace(source, destination):
            if Path(destination) == self.state:
                raise OSError("injected final replace failure")
            return real_replace(source, destination)

        with mock.patch("app.os.replace", side_effect=fail_final_replace):
            with self.assertRaisesRegex(OSError, "injected"):
                self.reserve(1)
        self.assertEqual(self.store.state, before_memory)
        self.assertEqual(self.state.read_bytes(), before_disk)
        self.assertEqual(
            StateStore(self.config, self.state, self.secret, self.clock).state,
            before_memory,
        )

    def test_concurrent_release_has_exactly_one_winner(self):
        result = self.reserve(1)
        barrier = threading.Barrier(8)
        outcomes = []

        def contender():
            barrier.wait()
            try:
                self.store.release(result["capability"])
                outcomes.append("released")
            except RackError as exc:
                outcomes.append(exc.code)

        threads = [threading.Thread(target=contender) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(outcomes.count("released"), 1)
        self.assertEqual(outcomes.count("invalid_capability"), 7)
        self.assertEqual(self.store.state["leases"], [])

    def test_corrupt_current_fails_closed_instead_of_loading_stale_backup(self):
        self.reserve(1)
        self.store.reserve("mira", 1, 60, "another-key-12345")
        self.state.write_text("broken")
        with self.assertRaisesRegex(ValueError, "refusing stale recovery"):
            StateStore(self.config, self.state, self.secret, self.clock)

    def test_missing_current_fails_closed(self):
        self.reserve(1)
        self.state.unlink()
        with self.assertRaisesRegex(ValueError, "missing; refusing stale recovery"):
            StateStore(self.config, self.state, self.secret, self.clock)

    def test_final_device_race_has_one_winner(self):
        self.reserve(2)
        barrier = threading.Barrier(8)
        outcomes = []

        def contender(index):
            barrier.wait()
            try:
                self.store.reserve(f"user{index}", 1, 60, f"concurrent-key-{index:03d}")
                outcomes.append("won")
            except RackError as exc:
                outcomes.append(exc.status)

        threads = [threading.Thread(target=contender, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(outcomes.count("won"), 1)
        self.assertEqual(outcomes.count(409), 7)

    def test_validation_boundaries(self):
        cases = [
            ("a", 1, 60, "abcdefghijklmnop"),
            ("alex", True, 60, "abcdefghijklmnop"),
            ("alex", 4, 60, "abcdefghijklmnop"),
            ("alex", 1, 31, "abcdefghijklmnop"),
            ("alex", 1, 60, "short"),
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(RackError):
                self.store.reserve(*args)
        self.assertEqual(self.store.state["leases"], [])


class CliTest(unittest.TestCase):
    def test_init_command_creates_explicit_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "app.py"),
                    "init",
                    "--config",
                    str(ROOT / "config.json"),
                    "--state",
                    str(root / "state.json"),
                    "--secret",
                    str(root / "secret.key"),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "state.json").is_file())
            self.assertEqual((root / "secret.key").stat().st_mode & 0o777, 0o600)


class ScaleTest(unittest.TestCase):
    def test_twenty_simultaneous_users_allocate_one_hundred_devices_without_overlap(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "gateway_host": "gateway.invalid",
                        "gateway_port": 22,
                        "default_lease_minutes": 60,
                        "max_lease_minutes": 1440,
                        "max_devices_per_reservation": 100,
                        "devices": [
                            {
                                "name": f"NUT{i:03d}",
                                "host": f"127.88.0.{i}",
                                "model": "comma 4",
                                "expected_ftdi_serial": f"NUT{i:03d}",
                            }
                            for i in range(1, 101)
                        ],
                    }
                )
            )
            state, secret = root / "state.json", root / "secret"
            StateStore.initialize(state, secret)
            store = StateStore(Config.load(config_path), state, secret)
            barrier = threading.Barrier(20)
            results, failures = [], []

            def reserve_five(index):
                barrier.wait()
                try:
                    results.append(
                        store.reserve(
                            f"user-{index:02d}", 5, 60, f"scale-user-key-{index:03d}"
                        )
                    )
                except Exception as exc:
                    failures.append(exc)

            threads = [
                threading.Thread(target=reserve_five, args=(i,)) for i in range(20)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(failures, [])
            assigned = [device for result in results for device in result["devices"]]
            self.assertEqual(len(assigned), 100)
            self.assertEqual(len(set(assigned)), 100)
            self.assertEqual(len(store.state["leases"]), 20)


if __name__ == "__main__":
    unittest.main()
