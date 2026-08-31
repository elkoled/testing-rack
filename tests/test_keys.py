import base64
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class KeyTest(unittest.TestCase):
    def run_key(self, key_type, value):
        return subprocess.run(
            [sys.executable, ROOT / "keys.py", key_type, value],
            text=True,
            capture_output=True,
        )

    def test_ordinary_key_is_accepted(self):
        value = base64.b64encode(b"x" * 32).decode()
        result = self.run_key("ssh-ed25519", value)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, f"ssh-ed25519 {value}\n")

    def test_invalid_and_obsolete_keys_are_rejected(self):
        value = base64.b64encode(b"x" * 32).decode()
        for key_type, key in (("ssh-dss", value), ("ssh-ed25519", "invalid")):
            with self.subTest(key_type=key_type, key=key):
                self.assertNotEqual(self.run_key(key_type, key).returncode, 0)
