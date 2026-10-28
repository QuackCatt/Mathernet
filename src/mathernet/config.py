from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path | None = None) -> None:
    env_path = path or Path(".env")
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


@dataclass(frozen=True, slots=True)
class Settings:
    data_path: Path
    gateway_path: Path
    request_timeout_seconds: int

    @classmethod
    def from_env(cls, dotenv_path: Path | None = None) -> "Settings":
        _load_dotenv(dotenv_path)
        data_path = Path(os.getenv("MATHERNET_DATA_PATH", "data/mathernet.json"))
        gateway_path = Path(
            os.getenv("MATHERNET_GATEWAY_PATH", str(data_path.parent / "gateway.json"))
        )
        return cls(
            data_path=data_path,
            gateway_path=gateway_path,
            request_timeout_seconds=int(os.getenv("MATHERNET_TIMEOUT_SECONDS", "30")),
        )
