import os
import sys
import unittest
from unittest import mock

import gateway


class GatewayTest(unittest.TestCase):
    def test_final_target_uses_comma_serial(self):
        reservation = {
            "display_id": "TEST",
            "devices": ["NUT001"],
            "expires_at": 2_000_000_000,
        }
        target = {
            "name": "NUT001",
            "serial": "6f9f27a9",
            "ftdi_serial": "DK0CFVDW",
            "health": "ready",
        }
        completed = mock.Mock(returncode=0)
        with (
            mock.patch.object(sys, "argv", ["gateway.py"]),
            mock.patch.dict(
                os.environ,
                {"SSH_ORIGINAL_COMMAND": "7Km3P9xQvT2w-NUT001"},
                clear=False,
            ),
            mock.patch.object(gateway, "request", side_effect=[reservation, target]),
            mock.patch.object(gateway.subprocess, "run", return_value=completed) as run,
            self.assertRaises(SystemExit) as stopped,
        ):
            gateway.main()
        self.assertEqual(stopped.exception.code, 0)
        self.assertEqual(run.call_args.args[0][-1], "comma@comma-6f9f27a9")


if __name__ == "__main__":
    unittest.main()
