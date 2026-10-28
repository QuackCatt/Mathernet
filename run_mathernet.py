#!/usr/bin/env python3
"""Windows-friendly entry point for Mathernet."""

from pathlib import Path
import sys


if sys.version_info < (3, 11):
    print("Mathernet requires Python 3.11 or newer.", file=sys.stderr)
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from mathernet.launcher import main


if __name__ == "__main__":
    raise SystemExit(main())
