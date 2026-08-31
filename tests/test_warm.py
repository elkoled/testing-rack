import unittest
from pathlib import Path
import tempfile

from warm import command, write_health


class WarmTest(unittest.TestCase):
    def test_connection_is_named_by_abstraction(self):
        result = command(
            {"name": "NUT004", "serial": "d05bb90f"},
            "/key",
            Path("/connections"),
        )
        self.assertIn("/connections/NUT004", result)
        self.assertEqual(result[-1], "comma@comma-d05bb90f")
        self.assertIn("ServerAliveInterval=15", result)

    def test_health_file_is_private_and_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "health.json"
            write_health(path, {"NUT001": "offline"})
            self.assertEqual(path.read_text(), '{"NUT001":"offline"}')
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)


if __name__ == "__main__":
    unittest.main()
