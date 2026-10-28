import errno
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from mathernet.config import Settings
from mathernet.launcher import build_parser, start_api


class FakeServer:
    def __init__(self, address):
        self.server_address = address
        self.closed = False

    def serve_forever(self):
        return None

    def server_close(self):
        self.closed = True


class LauncherTests(unittest.TestCase):
    def test_only_the_start_command_is_available(self):
        args = build_parser().parse_args(["start"])
        self.assertEqual(args.command, "start")
        for command in ("doctor", "list", "learn", "evaluate"):
            with self.subTest(command=command):
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    build_parser().parse_args([command])

    def test_start_prints_the_actual_url_and_port(self):
        settings = Settings.from_env()
        server = FakeServer(("127.0.0.1", 8765))
        output = io.StringIO()
        with (
            patch("mathernet.launcher.build_service", return_value=object()),
            patch("mathernet.launcher.create_server", return_value=server),
            redirect_stdout(output),
        ):
            result = start_api(settings)

        self.assertEqual(result, 0)
        self.assertTrue(server.closed)
        self.assertIn("URL: http://127.0.0.1:8765", output.getvalue())
        self.assertNotIn("Port:", output.getvalue())

    def test_busy_port_advances_and_only_the_url_is_printed(self):
        settings = Settings.from_env()
        server = FakeServer(("127.0.0.1", 8766))
        output = io.StringIO()
        with (
            patch("mathernet.launcher.build_service", return_value=object()),
            patch(
                "mathernet.launcher.create_server",
                side_effect=[OSError(errno.EADDRINUSE, "address in use"), server],
            ),
            redirect_stdout(output),
        ):
            result = start_api(settings)

        self.assertEqual(result, 0)
        self.assertTrue(server.closed)
        self.assertIn("URL: http://127.0.0.1:8766", output.getvalue())
        self.assertNotIn("Port:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
