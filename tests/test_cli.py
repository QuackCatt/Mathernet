import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from mathernet.cli import build_parser, start_api
from mathernet.config import Settings


class FakeServer:
    def __init__(self, address):
        self.server_address = address
        self.closed = False

    def serve_forever(self):
        return None

    def server_close(self):
        self.closed = True


class CliTests(unittest.TestCase):
    def test_start_command_replaces_the_demo_and_serve_setup_flow(self):
        args = build_parser().parse_args(["start", "--port", "9000"])
        self.assertEqual(args.command, "start")
        self.assertEqual(args.port, 9000)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(["demo"])

    def test_start_prints_the_actual_url_and_port(self):
        settings = Settings.from_env()
        server = FakeServer(("127.0.0.1", 8765))
        output = io.StringIO()
        with (
            patch("mathernet.cli.build_service", return_value=object()),
            patch("mathernet.cli.create_server", return_value=server),
            redirect_stdout(output),
        ):
            result = start_api(settings, host="127.0.0.1", port=8765)

        self.assertEqual(result, 0)
        self.assertTrue(server.closed)
        self.assertIn("URL: http://127.0.0.1:8765", output.getvalue())
        self.assertIn("Port: 8765", output.getvalue())


if __name__ == "__main__":
    unittest.main()
