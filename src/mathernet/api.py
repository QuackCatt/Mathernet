from __future__ import annotations

import json
import logging
import mimetypes
import re
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from pathlib import Path

from .errors import (
    ConflictError,
    MathernetError,
    NotFoundError,
    RetrievalError,
    StorageError,
    SynthesisError,
    ValidationError,
    RefusalError,
)
from .services import MathernetService


LOGGER = logging.getLogger(__name__)
MAX_REQUEST_BODY_BYTES = 1_000_000
DEFAULT_WEB_ROOT = Path(__file__).resolve().with_name("web")


@dataclass(slots=True)
class ApiResponse:
    status: int
    payload: dict[str, Any] | list[Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)


def handle_api_request(
    service: MathernetService,
    method: str,
    target: str,
    body: dict[str, Any] | None = None,
) -> ApiResponse:
    method = method.upper()
    parsed = urlsplit(target)
    path = unquote(parsed.path).rstrip("/") or "/"
    query = parse_qs(parsed.query, keep_blank_values=True)
    try:
        if method == "OPTIONS":
            return ApiResponse(204)
        if path == "/api/health" and method == "GET":
            return ApiResponse(200, service.health())
        if path == "/api/openapi.json" and method == "GET":
            return ApiResponse(200, openapi_document())
        if path == "/api/gateway" and method == "GET":
            return ApiResponse(200, service.gateway_config())
        if path == "/api/gateway" and method == "PATCH":
            return ApiResponse(200, service.save_gateway_config(body or {}))
        if path == "/api/gateway/models" and method == "POST":
            return ApiResponse(200, service.list_provider_models(body or {}))
        if path == "/api/gateway/mcp" and method == "PATCH":
            return ApiResponse(200, service.save_gateway_config(body or {}))
        if path == "/api/gateway/test-ai" and method == "POST":
            return ApiResponse(200, service.test_gateway_ai())
        if path == "/api/gateway/test-search" and method == "POST":
            return ApiResponse(200, service.test_gateway_search())
        if path == "/api/formulas" and method == "GET":
            return ApiResponse(
                200,
                service.list_formulas(
                    query=_query_value(query, "query", ""),
                    status=_query_value(query, "status"),
                    topic=_query_value(query, "topic"),
                    limit=_query_integer(query, "limit", 50),
                    offset=_query_integer(query, "offset", 0),
                ),
            )
        if path == "/api/learn" and method == "POST":
            payload = _require_body(body, {"query"}, {"map_session_id", "candidate"})
            result = service.learn(
                _required_string(payload, "query"),
                map_session_id=_optional_string(payload, "map_session_id"),
                candidate=payload.get("candidate"),
            )
            return ApiResponse(201 if result["created"] else 200, result)

        if path == "/api/learn/candidates" and method == "POST":
            payload = _require_body(body, {"query"}, set())
            return ApiResponse(
                200,
                service.discover_formula_candidates(_required_string(payload, "query")),
            )
        if path == "/api/export" and method == "GET":
            return ApiResponse(200, service.export_graph())

        if path == "/api/map-sessions" and method == "GET":
            return ApiResponse(200, service.list_map_sessions())
        if path == "/api/map-sessions" and method == "POST":
            payload = _require_body(body, {"name"}, set())
            return ApiResponse(201, service.create_map_session(_required_string(payload, "name")))

        map_session_match = re.fullmatch(r"/api/map-sessions/([^/]+)", path)
        if map_session_match:
            session_id = map_session_match.group(1)
            if method == "GET":
                return ApiResponse(200, service.get_map_session(session_id))
            if method == "PATCH":
                payload = _require_body(body, set(), {"name", "pinned"})
                name = _optional_string(payload, "name")
                pinned = payload.get("pinned")
                if pinned is not None and not isinstance(pinned, bool):
                    raise ValidationError("pinned must be a boolean")
                return ApiResponse(
                    200,
                    service.update_map_session(session_id, name=name, pinned=pinned),
                )
            if method == "DELETE":
                return ApiResponse(200, service.delete_map_session(session_id))

        map_formula_match = re.fullmatch(r"/api/map-sessions/([^/]+)/formulas", path)
        if map_formula_match and method == "POST":
            payload = _require_body(body, {"formula_id"}, set())
            return ApiResponse(
                200,
                service.add_formula_to_map_session(
                    map_formula_match.group(1),
                    _required_string(payload, "formula_id"),
                ),
            )

        map_graph_match = re.fullmatch(r"/api/map-sessions/([^/]+)/graph", path)
        if map_graph_match and method == "GET":
            return ApiResponse(200, service.get_map_graph(map_graph_match.group(1)))

        formula_match = re.fullmatch(r"/api/formulas/([^/]+)", path)
        if formula_match:
            if method == "GET":
                return ApiResponse(200, service.get_formula_card(formula_match.group(1)))
            if method == "DELETE":
                return ApiResponse(200, service.delete_formula(formula_match.group(1)))

        graph_match = re.fullmatch(r"/api/formulas/([^/]+)/graph", path)
        if graph_match and method == "GET":
            return ApiResponse(
                200,
                service.get_graph(
                    graph_match.group(1),
                    depth=_query_integer(query, "depth", 1),
                ),
            )

        introduction_match = re.fullmatch(r"/api/formulas/([^/]+)/introduction", path)
        if introduction_match and method == "POST":
            _require_body(body, set(), set())
            return ApiResponse(200, service.get_formula_introduction(introduction_match.group(1)))

        deep_sessions_match = re.fullmatch(r"/api/formulas/([^/]+)/deep-dive/sessions", path)
        if deep_sessions_match:
            if method == "GET":
                return ApiResponse(200, {"sessions": service.list_deep_dive_sessions(deep_sessions_match.group(1))})
            if method == "POST":
                _require_body(body, set(), set())
                return ApiResponse(201, service.create_deep_dive_session(deep_sessions_match.group(1)))

        deep_session_match = re.fullmatch(r"/api/formulas/([^/]+)/deep-dive/sessions/([^/]+)", path)
        if deep_session_match:
            formula_id, session_id = deep_session_match.groups()
            if method == "GET":
                return ApiResponse(200, service.get_deep_dive_session(formula_id, session_id))
            if method == "DELETE":
                return ApiResponse(200, service.delete_deep_dive_session(formula_id, session_id))

        deep_chat_match = re.fullmatch(r"/api/formulas/([^/]+)/deep-dive/sessions/([^/]+)/chat", path)
        if deep_chat_match and method == "POST":
            payload = _require_body(body, {"message"}, set())
            return ApiResponse(
                200,
                service.chat_deep_dive(
                    deep_chat_match.group(1),
                    deep_chat_match.group(2),
                    _required_string(payload, "message"),
                ),
            )

        user_module_match = re.fullmatch(r"/api/formulas/([^/]+)/user-module", path)
        if user_module_match and method == "PATCH":
            payload = _require_body(body, {"notes"}, {"expected_updated_at"})
            return ApiResponse(
                200,
                service.update_user_module(
                    user_module_match.group(1),
                    _required_string(payload, "notes", allow_empty=True),
                    expected_updated_at=_optional_string(payload, "expected_updated_at"),
                ),
            )

        status_match = re.fullmatch(r"/api/formulas/([^/]+)/status", path)
        if status_match and method == "PATCH":
            payload = _require_body(body, {"status"}, {"expected_updated_at"})
            return ApiResponse(
                200,
                service.set_formula_status(
                    status_match.group(1),
                    _required_string(payload, "status"),
                    expected_updated_at=_optional_string(payload, "expected_updated_at"),
                ),
            )

        if path == "/api/edges" and method == "POST":
            payload = _require_body(
                body,
                {"source_id", "target_id", "relation", "rationale", "source_ids"},
                {"edge_id", "manual"},
            )
            source_ids = payload["source_ids"]
            _require_string_array(payload, "source_ids")
            manual = payload.get("manual", False)
            if not isinstance(manual, bool):
                raise ValidationError("manual must be a boolean")
            rationale = payload.get("rationale")
            if not isinstance(rationale, str):
                raise ValidationError("rationale must be a string")
            return ApiResponse(
                201,
                service.add_edge(
                    source_ref=_required_string(payload, "source_id"),
                    target_ref=_required_string(payload, "target_id"),
                    relation=_required_string(payload, "relation"),
                    rationale=rationale,
                    source_ids=source_ids,
                    edge_id=_optional_string(payload, "edge_id"),
                    manual=manual,
                ),
            )

        relationship_deep_sessions_match = re.fullmatch(
            r"/api/edges/([^/]+)/deep-dive/sessions",
            path,
        )
        if relationship_deep_sessions_match:
            edge_id = relationship_deep_sessions_match.group(1)
            if method == "GET":
                return ApiResponse(
                    200,
                    {
                        "sessions": service.list_relationship_deep_dive_sessions(
                            edge_id
                        )
                    },
                )
            if method == "POST":
                _require_body(body, set(), set())
                return ApiResponse(
                    201,
                    service.create_relationship_deep_dive_session(edge_id),
                )

        relationship_deep_session_match = re.fullmatch(
            r"/api/edges/([^/]+)/deep-dive/sessions/([^/]+)",
            path,
        )
        if relationship_deep_session_match:
            edge_id, session_id = relationship_deep_session_match.groups()
            if method == "GET":
                return ApiResponse(
                    200,
                    service.get_relationship_deep_dive_session(edge_id, session_id),
                )
            if method == "DELETE":
                return ApiResponse(
                    200,
                    service.delete_relationship_deep_dive_session(edge_id, session_id),
                )

        relationship_deep_chat_match = re.fullmatch(
            r"/api/edges/([^/]+)/deep-dive/sessions/([^/]+)/chat",
            path,
        )
        if relationship_deep_chat_match and method == "POST":
            payload = _require_body(body, {"message"}, set())
            edge_id, session_id = relationship_deep_chat_match.groups()
            return ApiResponse(
                200,
                service.chat_relationship_deep_dive(
                    edge_id,
                    session_id,
                    _required_string(payload, "message"),
                ),
            )

        edge_match = re.fullmatch(r"/api/edges/([^/]+)", path)
        if edge_match and method == "GET":
            return ApiResponse(200, service.get_edge_payload(edge_match.group(1)))

        if edge_match and method == "DELETE":
            payload = _require_body(body, set(), {"expected_updated_at"})
            return ApiResponse(
                200,
                service.delete_edge(
                    edge_match.group(1),
                    expected_updated_at=_optional_string(payload, "expected_updated_at"),
                ),
            )

        if edge_match and method == "PATCH":
            payload = _require_body(
                body,
                {"relation", "rationale", "source_ids"},
                {"expected_updated_at"},
            )
            source_ids = _require_string_array(payload, "source_ids")
            return ApiResponse(
                200,
                service.update_edge(
                    edge_match.group(1),
                    relation=_required_string(payload, "relation"),
                    rationale=_required_string(payload, "rationale"),
                    source_ids=source_ids,
                    expected_updated_at=_optional_string(payload, "expected_updated_at"),
                ),
            )

        edge_action_match = re.fullmatch(r"/api/edges/([^/]+)/(confirm|reject)", path)
        if edge_action_match and method == "POST":
            payload = _require_body(body, set(), {"expected_updated_at"})
            expected_updated_at = _optional_string(payload, "expected_updated_at")
            if edge_action_match.group(2) == "confirm":
                result = service.confirm_edge(
                    edge_action_match.group(1),
                    expected_updated_at=expected_updated_at,
                )
            else:
                result = service.reject_edge(
                    edge_action_match.group(1),
                    expected_updated_at=expected_updated_at,
                )
            return ApiResponse(200, result)

        raise NotFoundError(f"API route {method} {path} was not found")
    except RefusalError as error:
        return ApiResponse(
            422,
            {
                "error": {
                    "code": "refused",
                    "message": str(error),
                    "reason_code": error.reason_code,
                }
            },
        )
    except ConflictError as error:
        return _error_response(409, "conflict", error)
    except NotFoundError as error:
        return _error_response(404, "not_found", error)
    except ValidationError as error:
        return _error_response(400, "validation_error", error)
    except (RetrievalError, SynthesisError) as error:
        return _error_response(502, "upstream_error", error)
    except StorageError as error:
        return _error_response(500, "storage_error", error)
    except MathernetError as error:
        return _error_response(500, "internal_error", error)
    except Exception:
        LOGGER.exception("Unhandled API failure for %s %s", method, path)
        return ApiResponse(
            500,
            {"error": {"code": "internal_error", "message": "unexpected server error"}},
        )


def openapi_document() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Mathernet local API",
            "version": "1.0.0",
            "description": "JSON API for a source-backed formula knowledge graph.",
        },
        "paths": {
            "/api/health": {"get": {"summary": "Service and graph health"}},
            "/api/gateway": {
                "get": {"summary": "Read masked AI and search gateway settings"},
                "patch": {"summary": "Save AI and search gateway settings"},
            },
            "/api/gateway/models": {
                "post": {"summary": "List models exposed by the selected AI provider"}
            },
            "/api/gateway/mcp": {"patch": {"summary": "Save MCP search gateway settings"}},
            "/api/gateway/test-ai": {"post": {"summary": "Test the configured AI provider"}},
            "/api/gateway/test-search": {"post": {"summary": "Test the configured search connection"}},
            "/api/formulas": {"get": {"summary": "Search and page formula summaries"}},
            "/api/learn": {"post": {"summary": "Create or reuse a source-backed formula card"}},
            "/api/learn/candidates": {
                "post": {"summary": "Find formula candidates without creating cards"}
            },
            "/api/map-sessions": {
                "get": {"summary": "List mind-map sessions"},
                "post": {"summary": "Create a mind-map session"},
            },
            "/api/map-sessions/{session_id}": {
                "get": {"summary": "Read one mind-map session"},
                "patch": {"summary": "Rename or pin a mind-map session"},
                "delete": {"summary": "Delete a mind-map session"},
            },
            "/api/map-sessions/{session_id}/formulas": {
                "post": {"summary": "Add a formula card to a mind-map session"}
            },
            "/api/map-sessions/{session_id}/graph": {
                "get": {"summary": "Read the complete active mind-map graph"}
            },
            "/api/formulas/{formula_id}": {
                "get": {"summary": "Read a complete formula card"},
                "delete": {"summary": "Delete a formula card globally"},
            },
            "/api/formulas/{formula_id}/graph": {"get": {"summary": "Read a bounded graph neighbourhood"}},
            "/api/formulas/{formula_id}/introduction": {
                "post": {"summary": "Generate or reuse a concise formula introduction"}
            },
            "/api/formulas/{formula_id}/deep-dive/sessions": {
                "get": {"summary": "List preserved deep-dive sessions"},
                "post": {"summary": "Generate a new deep-dive session"},
            },
            "/api/formulas/{formula_id}/deep-dive/sessions/{session_id}": {
                "get": {"summary": "Read one deep-dive session"},
                "delete": {"summary": "Delete one deep-dive session"},
            },
            "/api/formulas/{formula_id}/deep-dive/sessions/{session_id}/chat": {
                "post": {"summary": "Continue a deep-dive session conversation"}
            },
            "/api/formulas/{formula_id}/user-module": {"patch": {"summary": "Update personal notes"}},
            "/api/formulas/{formula_id}/status": {"patch": {"summary": "Update study status"}},
            "/api/edges": {"post": {"summary": "Propose a source-backed dependency edge"}},
            "/api/edges/{edge_id}": {
                "get": {"summary": "Read one dependency edge"},
                "patch": {"summary": "Edit and explicitly accept an edge"},
                "delete": {"summary": "Delete a dependency edge"},
            },
            "/api/edges/{edge_id}/confirm": {"post": {"summary": "Explicitly confirm an AI-suggested edge"}},
            "/api/edges/{edge_id}/reject": {"post": {"summary": "Reject an AI-suggested edge"}},
            "/api/edges/{edge_id}/deep-dive/sessions": {
                "get": {"summary": "List saved relationship deep-dive sessions"},
                "post": {"summary": "Generate a relationship deep-dive session"},
            },
            "/api/edges/{edge_id}/deep-dive/sessions/{session_id}": {
                "get": {"summary": "Read one relationship deep-dive session"},
                "delete": {"summary": "Delete one relationship deep-dive session"},
            },
            "/api/edges/{edge_id}/deep-dive/sessions/{session_id}/chat": {
                "post": {"summary": "Continue a relationship deep-dive conversation"}
            },
            "/api/export": {"get": {"summary": "Export the full schema-v1 graph"}},
        },
        "components": {
            "schemas": {
                "Error": {
                    "type": "object",
                    "required": ["error"],
                    "properties": {
                        "error": {
                            "type": "object",
                            "required": ["code", "message"],
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                                "reason_code": {"type": "string"},
                            },
                        }
                    },
                }
            }
        },
    }


def create_server(
    service: MathernetService,
    host: str = "127.0.0.1",
    port: int = 8765,
    web_root: Path | str | None = None,
) -> ThreadingHTTPServer:
    return MathernetHTTPServer((host, port), service, Path(web_root or DEFAULT_WEB_ROOT))


def resolve_web_asset(web_root: Path | str, request_path: str) -> Path:
    root = Path(web_root).resolve()
    decoded = unquote(request_path).lstrip("/")
    relative = "index.html" if decoded in {"", "."} else decoded
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise NotFoundError("static asset was not found") from error
    if any(part.startswith(".") for part in candidate.relative_to(root).parts):
        raise NotFoundError("static asset was not found")
    if candidate.is_dir():
        candidate = candidate / "index.html"
    if not candidate.is_file():
        raise NotFoundError("static asset was not found")
    return candidate


class MathernetHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        service: MathernetService,
        web_root: Path,
    ):
        self.service = service
        self.web_root = web_root
        super().__init__(address, MathernetRequestHandler)


class MathernetRequestHandler(BaseHTTPRequestHandler):
    server: MathernetHTTPServer
    server_version = "Mathernet/1.0"
    sys_version = ""

    def do_GET(self) -> None:
        self._dispatch(None)

    def do_POST(self) -> None:
        self._dispatch_with_body()

    def do_PATCH(self) -> None:
        self._dispatch_with_body()

    def do_DELETE(self) -> None:
        self._dispatch_with_body()

    def do_OPTIONS(self) -> None:
        self._dispatch(None)

    def _dispatch(self, body: dict[str, Any] | None) -> None:
        parsed = urlsplit(self.path)
        if self.command == "GET" and not parsed.path.startswith("/api/"):
            self._send_static(parsed.path)
            return
        response = handle_api_request(self.server.service, self.command, self.path, body)
        self._send_response(response)

    def _dispatch_with_body(self) -> None:
        try:
            body = self._read_json_body()
        except MathernetError as error:
            self._send_response(_error_response(400, "validation_error", error))
            return
        self._dispatch(body)

    def _send_response(self, response: ApiResponse) -> None:
        payload = b"" if response.payload is None else json.dumps(
            response.payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(response.status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, If-Match")
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def _send_static(self, request_path: str) -> None:
        try:
            asset = resolve_web_asset(self.server.web_root, request_path)
        except NotFoundError:
            self._send_response(_error_response(404, "not_found", NotFoundError("page was not found")))
            return
        try:
            payload = asset.read_bytes()
        except OSError:
            self._send_response(
                _error_response(500, "storage_error", StorageError("could not read web asset"))
            )
            return
        content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; connect-src 'self'; img-src 'self' data:; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as error:
            raise ValidationError("Content-Length must be an integer") from error
        if length < 0 or length > MAX_REQUEST_BODY_BYTES:
            raise ValidationError(
                f"request body must be at most {MAX_REQUEST_BODY_BYTES} bytes"
            )
        if length == 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValidationError("request body must be valid UTF-8 JSON") from error
        if not isinstance(payload, dict):
            raise ValidationError("request body must be a JSON object")
        return payload

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.info("%s - %s", self.address_string(), format % args)


def _require_body(
    body: dict[str, Any] | None,
    required: set[str],
    optional: set[str],
) -> dict[str, Any]:
    payload = body or {}
    missing = required - payload.keys()
    if missing:
        raise ValidationError(f"missing required fields: {', '.join(sorted(missing))}")
    unknown = payload.keys() - required - optional
    if unknown:
        raise ValidationError(f"unknown fields: {', '.join(sorted(unknown))}")
    return payload


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{key} must be a string")
    return value


def _required_string(
    payload: dict[str, Any],
    key: str,
    *,
    allow_empty: bool = False,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValidationError(f"{key} must be a string")
    if not value and not allow_empty:
        raise ValidationError(f"{key} must not be empty")
    return value


def _require_string_array(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValidationError(f"{key} must be an array of strings")
    return value


def _query_value(
    query: dict[str, list[str]],
    key: str,
    default: str | None = None,
) -> str | None:
    values = query.get(key)
    if not values:
        return default
    return values[-1]


def _query_integer(
    query: dict[str, list[str]],
    key: str,
    default: int,
) -> int:
    value = _query_value(query, key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ValidationError(f"{key} must be an integer") from error


def _error_response(status: int, code: str, error: Exception) -> ApiResponse:
    return ApiResponse(status, {"error": {"code": code, "message": str(error)}})
