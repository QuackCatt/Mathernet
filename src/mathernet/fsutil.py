from __future__ import annotations

import os
from pathlib import Path


def chmod_private(path: Path | str) -> None:
    """Best-effort 0600 permissions.

    Windows only models the read-only bit, so a failed chmod there must not
    stop local persistence. On POSIX a failure is still surfaced.
    """
    try:
        os.chmod(path, 0o600)
    except OSError:
        if os.name != "nt":
            raise
