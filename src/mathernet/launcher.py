from __future__ import annotations

import argparse
import errno
import shutil
import sys
from pathlib import Path

from .api import create_server
from .config import Settings
from .errors import MathernetError
from .repository import GraphRepository
from .services import build_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mathernet",
        description="Start the Mathernet web application.",
    )
    parser.add_argument("command", choices=("start",), help="start Mathernet")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _initialize()
        return start_api(Settings.from_env())
    except MathernetError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


def _initialize() -> None:
    Path("data").mkdir(exist_ok=True)
    if not Path(".env").exists() and Path(".env.example").exists():
        shutil.copyfile(".env.example", ".env")
    settings = Settings.from_env()
    settings.data_path.parent.mkdir(parents=True, exist_ok=True)
    GraphRepository(settings.data_path).save()


def start_api(settings: Settings) -> int:
    service = build_service(settings)
    server = None
    last_error = None
    for port in range(8765, 8785):
        try:
            server = create_server(service, host="127.0.0.1", port=port)
            break
        except OSError as error:
            if error.errno not in {errno.EADDRINUSE, errno.EACCES}:
                raise MathernetError(f"could not start Mathernet: {error}") from error
            last_error = error
    if server is None:
        raise MathernetError(
            f"could not find an available port near 8765: {last_error or 'unknown error'}"
        )

    address, actual_port = server.server_address[:2]
    display_host = "127.0.0.1" if address in {"0.0.0.0", "::"} else address
    print("Mathernet is running.")
    print(f"URL: http://{display_host}:{actual_port}")
    print(f"Port: {actual_port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nMathernet stopped.")
    finally:
        server.server_close()
    return 0
