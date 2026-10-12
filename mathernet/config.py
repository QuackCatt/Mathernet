from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path


DEFAULT_APPROVED_PUBLISHERS = (
    "Wikipedia",
    "Wolfram MathWorld",
    "Khan Academy",
    "MIT OpenCourseWare",
    "Stanford Encyclopedia of Philosophy",
    "University",
)


def _load_dotenv(path: Path | None = None) -> None:
    env_path = path or Path(".env")
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
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
    search_cache_path: Path
    mcp_transport: str
    mcp_command: tuple[str, ...]
    mcp_http_url: str
    mcp_tool_name: str
    mcp_headers: str
    openai_api_key: str
    openai_model: str
    approved_publishers: tuple[str, ...]
    request_timeout_seconds: int

    @classmethod
    def from_env(cls, dotenv_path: Path | None = None) -> "Settings":
        _load_dotenv(dotenv_path)
        command_value = os.getenv("MCP_SERVER_COMMAND", "")
        command = tuple(shlex.split(command_value)) if command_value else ()
        publishers = tuple(
            item.strip()
            for item in os.getenv(
                "MCP_APPROVED_PUBLISHERS", ",".join(DEFAULT_APPROVED_PUBLISHERS)
            ).split(",")
            if item.strip()
        )
        return cls(
            data_path=Path(os.getenv("MATHERNET_DATA_PATH", "data/mathernet.json")),
            search_cache_path=Path(
                os.getenv("MATHERNET_SEARCH_CACHE_PATH", "data/search_cache.json")
            ),
            mcp_transport=os.getenv("MCP_TRANSPORT", "stdio").strip().lower(),
            mcp_command=command,
            mcp_http_url=os.getenv("MCP_HTTP_URL", "").strip(),
            mcp_tool_name=os.getenv("MCP_TOOL_NAME", "search").strip() or "search",
            mcp_headers=os.getenv("MCP_HTTP_HEADERS_JSON", "").strip(),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini").strip(),
            approved_publishers=publishers,
            request_timeout_seconds=int(os.getenv("MATHERNET_TIMEOUT_SECONDS", "30")),
        )
