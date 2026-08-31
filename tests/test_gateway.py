import io
import os
import sys
import time
import unittest
from unittest import mock

import gateway


class GatewayTest(unittest.TestCase):
    def test_active_session_heartbeat_refreshes_reservation(self):
        stop = mock.Mock()
        stop.wait.side_effect = [False, True]
        with mock.patch.object(gateway, "request") as request:
            gateway.keep_active(stop, "http://service", "token", "NUT001")
        request.assert_called_once_with(
            "http://service",
            "/api/gateway/resolve",
            "token",
            {"device": "NUT001"},
        )

    def test_final_target_uses_comma_serial(self):
        target = {
            "name": "NUT001",
            "serial": "6f9f27a9",
            "ftdi_serial": "DK0CFVDW",
            "health": "ready",
            "expires_at": time.time() + 3600,
            "display_name": "chestnut_rack",
        }
        completed = mock.Mock(returncode=0)
        with (
            mock.patch.object(sys, "argv", ["gateway.py"]),
            mock.patch.dict(
                os.environ,
                {"SSH_ORIGINAL_COMMAND": "7Km3P9xQvT2w-NUT001"},
                clear=False,
            ),
            mock.patch.object(gateway, "request", return_value=target) as request,
            mock.patch.object(gateway.subprocess, "run", return_value=completed) as run,
            mock.patch.object(sys, "stderr", io.StringIO()) as stderr,
            self.assertRaises(SystemExit) as stopped,
        ):
            gateway.main()
        self.assertEqual(stopped.exception.code, 0)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(run.call_args.args[0][-1], "comma@comma-6f9f27a9")
        self.assertNotIn("-tt", run.call_args.args[0])
        self.assertEqual(stderr.getvalue(), "chestnut_rack · NUT001\n")

    def test_hardware_action_is_scoped_and_delegated(self):
        target = {
            "name": "NUT001",
            "serial": "6f9f27a9",
            "ftdi_serial": "DK0CFVDW",
            "gpu_power_switch": "lower_1",
            "health": "ready",
            "expires_at": time.time() + 3600,
            "display_name": "chestnut_rack",
        }
        completed = mock.Mock(returncode=0)
        with (
            mock.patch.object(sys, "argv", ["gateway.py"]),
            mock.patch.dict(
                os.environ,
                {
                    "SSH_ORIGINAL_COMMAND": "7Km3P9xQvT2w-NUT001 gpu_power:off"
                },
                clear=False,
            ),
            mock.patch.object(gateway, "request", return_value=target),
            mock.patch.object(gateway.subprocess, "run", return_value=completed) as run,
            mock.patch.object(sys, "stderr", io.StringIO()),
            self.assertRaises(SystemExit) as stopped,
        ):
            gateway.main()
        self.assertEqual(stopped.exception.code, 0)
        self.assertEqual(
            run.call_args.args[0][-2:], ["NUT001", "gpu_power:off"]
        )

    def test_remote_command_is_forwarded_without_local_shell(self):
        target = {
            "name": "NUT001",
            "serial": "6f9f27a9",
            "health": "ready",
            "expires_at": time.time() + 3600,
            "display_name": "chestnut_rack",
        }
        completed = mock.Mock(returncode=7)
        command = "printf '%s\\n' agent-ok && uname -a"
        with (
            mock.patch.object(sys, "argv", ["gateway.py"]),
            mock.patch.dict(
                os.environ,
                {"SSH_ORIGINAL_COMMAND": f"7Km3P9xQvT2w-NUT001 {command}"},
                clear=False,
            ),
            mock.patch.object(gateway, "request", return_value=target),
            mock.patch.object(gateway.subprocess, "run", return_value=completed) as run,
            mock.patch.object(sys, "stderr", io.StringIO()),
            self.assertRaises(SystemExit) as stopped,
        ):
            gateway.main()
        self.assertEqual(stopped.exception.code, 7)
        self.assertEqual(run.call_args.args[0][-2:], ["comma@comma-6f9f27a9", command])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_misplaced_identity_option_is_ignored(self):
        target = {
            "name": "NUT001",
            "serial": "6f9f27a9",
            "health": "ready",
            "expires_at": time.time() + 3600,
            "display_name": "chestnut_rack",
        }
        completed = mock.Mock(returncode=0)
        with (
            mock.patch.object(sys, "argv", ["gateway.py"]),
            mock.patch.dict(
                os.environ,
                {
                    "SSH_ORIGINAL_COMMAND": (
                        "7Km3P9xQvT2w-NUT001 -i /home/alex/.ssh/xx_key"
                    )
                },
                clear=False,
            ),
            mock.patch.object(gateway, "request", return_value=target),
            mock.patch.object(gateway.subprocess, "run", return_value=completed) as run,
            mock.patch.object(sys, "stderr", io.StringIO()),
            self.assertRaises(SystemExit) as stopped,
        ):
            gateway.main()
        self.assertEqual(stopped.exception.code, 0)
        self.assertEqual(run.call_args.args[0][-1], "comma@comma-6f9f27a9")


if __name__ == "__main__":
    unittest.main()
