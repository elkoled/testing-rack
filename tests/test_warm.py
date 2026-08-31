import unittest
from pathlib import Path

from warm import command


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


if __name__ == "__main__":
    unittest.main()
