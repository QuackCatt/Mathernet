from __future__ import annotations

import hashlib
import json
import os
import select
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .config import Settings
from .errors import RetrievalError
from .models import SourceRecord
from .normalization import normalize_text


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    publisher: str
    excerpt: str
    retrieved_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
    )

    def to_source_record(self) -> SourceRecord:
        digest = hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:16]
        return SourceRecord(
            id=f"src_{digest}",
            title=self.title,
            url=self.url,
            publisher=self.publisher,
            retrieved_at=self.retrieved_at,
            excerpt=self.excerpt,
        )


class SearchProvider(Protocol):
    def search(self, query: str, limit: int = 5) -> list[SearchResult]: ...


class StaticSearchProvider:
    """Deterministic adapter for tests, demos, and cached research material."""

    def __init__(self, results: list[SearchResult] | None = None):
        self.results = results or []

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        normalized = normalize_text(query).casefold()
        matches = [
            result
            for result in self.results
            if normalized in normalize_text(f"{result.title} {result.excerpt}").casefold()
        ]
        return (matches or self.results)[:limit]


def parse_search_results(payload: Any) -> list[SearchResult]:
    if isinstance(payload, dict):
        raw_results = payload.get("results", payload.get("items", [payload]))
    else:
        raw_results = payload
    if not isinstance(raw_results, list):
        raise RetrievalError("MCP search response does not contain a result list")
    results: list[SearchResult] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        url = str(item.get("url") or item.get("link") or "").strip()
        publisher = str(item.get("publisher") or item.get("source") or "").strip()
        excerpt = str(
            item.get("excerpt")
            or item.get("snippet")
            or item.get("content")
            or item.get("description")
            or ""
        ).strip()
        if title and url and publisher and excerpt:
            results.append(
                SearchResult(
                    title,
                    url,
                    publisher,
                    excerpt,
                    str(
                        item.get("retrieved_at")
                        or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                    ),
                )
            )
    return results


class QuerySearchCache:
    SCHEMA_VERSION = 1
    MAX_ENTRIES = 200

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser()

    def load(self, query: str, limit: int) -> list[SearchResult]:
        entries = self._read()
        entry = entries.get(self._query_key(query))
        if not entry:
            return []
        return parse_search_results(entry.get("results", []))[:limit]

    def save(self, query: str, results: list[SearchResult]) -> None:
        if not results:
            return
        entries = self._read()
        entries[self._query_key(query)] = {
            "query": normalize_text(query),
            "cached_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "results": [asdict(result) for result in results],
        }
        if len(entries) > self.MAX_ENTRIES:
            ordered = sorted(
                entries.items(),
                key=lambda item: item[1].get("cached_at", ""),
            )
            entries = dict(ordered[-self.MAX_ENTRIES :])
        self._write(entries)

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RetrievalError(f"could not read search cache: {error}") from error
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != self.SCHEMA_VERSION
            or not isinstance(payload.get("queries"), dict)
        ):
            raise RetrievalError("search cache has an unsupported or invalid format")
        return payload["queries"]

    def _write(self, entries: dict[str, dict[str, Any]]) -> None:
        payload = json.dumps(
            {"schema_version": self.SCHEMA_VERSION, "queries": entries},
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temp_path = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, self.path)
        except OSError as error:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise RetrievalError(f"could not write search cache: {error}") from error

    @staticmethod
    def _query_key(query: str) -> str:
        normalized = normalize_text(query).casefold()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class CachingSearchProvider:
    def __init__(self, provider: SearchProvider, cache_path: Path | str):
        self.provider = provider
        self.cache = QuerySearchCache(cache_path)
        self._entered_provider: SearchProvider | None = None
        self._entry_error: RetrievalError | None = None

    def __enter__(self) -> "CachingSearchProvider":
        try:
            if hasattr(self.provider, "__enter__"):
                self._entered_provider = self.provider.__enter__()
            else:
                self._entered_provider = self.provider
        except RetrievalError as error:
            self._entry_error = error
        return self

    def __exit__(self, *_: object) -> None:
        if hasattr(self.provider, "__exit__"):
            self.provider.__exit__(None, None, None)
        self._entered_provider = None
        self._entry_error = None

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        provider = self._entered_provider or self.provider
        try:
            if self._entry_error is not None:
                raise self._entry_error
            results = provider.search(query, limit=limit)
        except RetrievalError:
            cached = self.cache.load(query, limit)
            if cached:
                return cached
            raise
        if results:
            self.cache.save(query, results[:limit])
        else:
            results = self.cache.load(query, limit)
        return results[:limit]


def filter_approved_sources(
    results: list[SearchResult], approved_publishers: tuple[str, ...]
) -> list[SearchResult]:
    approved = tuple(normalize_text(item).casefold() for item in approved_publishers)
    return [
        result
        for result in results
        if any(name in normalize_text(result.publisher).casefold() for name in approved)
    ]


class MCPStdioClient:
    def __init__(
        self,
        command: tuple[str, ...],
        tool_name: str = "search",
        timeout_seconds: int = 30,
    ):
        self.command = command
        self.tool_name = tool_name
        self.timeout_seconds = timeout_seconds
        self.process: subprocess.Popen[str] | None = None
        self.request_id = 0

    def __enter__(self) -> "MCPStdioClient":
        if not self.command:
            raise RetrievalError("MCP_SERVER_COMMAND is not configured")
        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except OSError as error:
            raise RetrievalError(f"could not start MCP server: {error}") from error
        self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "mathernet", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized", {})
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self.process is None:
            return
        process = self.process
        if process.stdin is not None:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        self.process = None

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        response = self._rpc(
            "tools/call",
            {"name": self.tool_name, "arguments": {"query": query, "limit": limit}},
        )
        result = response.get("result", {})
        content = result.get("content", [])
        payloads: list[Any] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                try:
                    payloads.append(json.loads(text))
                except json.JSONDecodeError:
                    payloads.append({"title": text, "url": "", "publisher": "", "excerpt": ""})
        if len(payloads) == 1:
            return parse_search_results(payloads[0])
        results: list[SearchResult] = []
        for payload in payloads:
            results.extend(parse_search_results(payload))
        return results

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.request_id += 1
        request_id = self.request_id
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        process = self.process
        if process is None or process.stdout is None:
            raise RetrievalError("MCP server is not running")
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RetrievalError("MCP server response timed out")
            ready, _, _ = select.select([process.stdout], [], [], remaining)
            if not ready:
                raise RetrievalError("MCP server response timed out")
            line = process.stdout.readline()
            if not line:
                stderr = process.stderr.read() if process.stderr else ""
                raise RetrievalError(f"MCP server closed unexpectedly: {stderr.strip()}")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RetrievalError(f"MCP request failed: {message['error']}")
            return message

    def _write(self, message: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.stdin is None:
            raise RetrievalError("MCP server is not running")
        try:
            process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except OSError as error:
            raise RetrievalError(f"could not write to MCP server: {error}") from error


class MCPHTTPClient:
    def __init__(
        self,
        url: str,
        tool_name: str = "search",
        headers_json: str = "",
        timeout_seconds: int = 30,
    ):
        self.url = url
        self.tool_name = tool_name
        self.timeout_seconds = timeout_seconds
        self.headers = json.loads(headers_json) if headers_json else {}
        self.session_id: str | None = None
        self.request_id = 0

    def __enter__(self) -> "MCPHTTPClient":
        if not self.url:
            raise RetrievalError("MCP_HTTP_URL is not configured")
        response = self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "mathernet", "version": "0.1.0"},
            },
            expect_session=True,
        )
        self._rpc("notifications/initialized", {}, notification=True)
        if "result" not in response:
            raise RetrievalError("MCP HTTP initialize response is invalid")
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        response = self._rpc(
            "tools/call",
            {"name": self.tool_name, "arguments": {"query": query, "limit": limit}},
        )
        result = response.get("result", {})
        content = result.get("content", [])
        payloads: list[Any] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                try:
                    payloads.append(json.loads(item.get("text", "")))
                except json.JSONDecodeError:
                    continue
        if len(payloads) == 1:
            return parse_search_results(payloads[0])
        results: list[SearchResult] = []
        for payload in payloads:
            results.extend(parse_search_results(payload))
        return results

    def _rpc(
        self,
        method: str,
        params: dict[str, Any],
        notification: bool = False,
        expect_session: bool = False,
    ) -> dict[str, Any]:
        self.request_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            message["id"] = self.request_id
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self.headers,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urllib.request.Request(
            self.url,
            data=json.dumps(message).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                if expect_session:
                    self.session_id = response.headers.get("Mcp-Session-Id")
                body = response.read().decode("utf-8")
        except (urllib.error.URLError, OSError) as error:
            raise RetrievalError(f"MCP HTTP request failed: {error}") from error
        if notification:
            return {}
        parsed = _parse_http_response(body)
        if "error" in parsed:
            raise RetrievalError(f"MCP request failed: {parsed['error']}")
        return parsed


def _parse_http_response(body: str) -> dict[str, Any]:
    stripped = body.strip()
    if not stripped:
        return {}
    if stripped.startswith("{"):
        value = json.loads(stripped)
        return value if isinstance(value, dict) else {"result": value}
    for line in stripped.splitlines():
        if line.startswith("data:"):
            value = json.loads(line[5:].strip())
            return value if isinstance(value, dict) else {"result": value}
    raise RetrievalError("MCP HTTP response is not JSON or server-sent events")


def provider_from_settings(settings: Settings) -> SearchProvider:
    if settings.mcp_transport == "stdio":
        return CachingSearchProvider(
            MCPStdioClient(
                settings.mcp_command,
                settings.mcp_tool_name,
                settings.request_timeout_seconds,
            ),
            settings.search_cache_path,
        )
    if settings.mcp_transport == "http":
        return CachingSearchProvider(
            MCPHTTPClient(
                settings.mcp_http_url,
                settings.mcp_tool_name,
                settings.mcp_headers,
                settings.request_timeout_seconds,
            ),
            settings.search_cache_path,
        )
    raise RetrievalError("MCP_TRANSPORT must be either stdio or http")


def load_cached_search_results(path: Path | str) -> list[SearchResult]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RetrievalError(f"could not load cached search results: {error}") from error
    return parse_search_results(payload)
