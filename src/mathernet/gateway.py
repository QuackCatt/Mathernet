from __future__ import annotations

import json
import os
import shlex
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent_skills import (
    FORMULA_CHAT_SKILL,
    FORMULA_CANDIDATE_SCHEMA,
    FORMULA_CANDIDATE_SKILL,
    FORMULA_DEEP_DIVE_SCHEMA,
    FORMULA_DEEP_DIVE_SKILL,
    FORMULA_DISCOVERY_SCHEMA,
    FORMULA_DISCOVERY_SKILL,
    FORMULA_INTRODUCTION_SCHEMA,
    FORMULA_INTRODUCTION_SKILL,
    RELATIONSHIP_DEEP_DIVE_SKILL,
    RELATIONSHIP_VALIDATION_SCHEMA,
    RELATIONSHIP_VALIDATION_SKILL,
    FormulaDiscovery,
    FormulaCandidate,
    build_formula_candidate_prompt,
    build_formula_chat_prompt,
    build_formula_deep_dive_prompt,
    build_formula_discovery_prompt,
    build_formula_introduction_prompt,
    build_formula_synthesis_prompt,
    build_relationship_deep_dive_prompt,
    build_relationship_validation_prompt,
    load_agent_skill,
    parse_formula_deep_dive,
    parse_formula_discovery,
    parse_formula_candidates,
    parse_formula_introduction,
    parse_relationship_validation,
)
from .errors import RetrievalError, SynthesisError, ValidationError
from .http_client import open_url
from .llm import SynthesisResult, parse_synthesis_result
from .providers import (
    PROVIDER_PRESETS,
    ProviderRequest,
    adapter_for_config,
    extract_provider_text,
    resolve_provider_config,
)
from .retrieval import MCPHTTPClient, MCPStdioClient, SearchResult, SearchProvider, parse_search_results


PROVIDERS = tuple(PROVIDER_PRESETS)
SEARCH_ENGINES = ("google", "bing", "yahoo", "baidu")
DEFAULT_MODELS = {name: preset.default_model for name, preset in PROVIDER_PRESETS.items()}
DEFAULT_ENDPOINTS = {name: preset.endpoint_path for name, preset in PROVIDER_PRESETS.items()}


@dataclass(slots=True)
class GatewayConfig:
    provider: str = ""
    api_key: str = ""
    model: str = ""
    api_format: str = ""
    base_url: str = ""
    endpoint_path: str = ""
    auth_style: str = ""
    search_engine: str = ""
    search_api_key: str = ""
    search_engine_id: str = ""
    mcp_transport: str = "stdio"
    mcp_command: str = ""
    mcp_http_url: str = ""
    mcp_tool_name: str = "search"
    mcp_headers: str = ""
    configured_at: str = ""
    ai_connection_status: str = "unknown"
    ai_connection_message: str = ""
    ai_connection_checked_at: str = ""

    def __post_init__(self) -> None:
        self.provider = self.provider.strip().lower()
        self.api_key = self.api_key.strip()
        self.model = self.model.strip()
        self.api_format = self.api_format.strip()
        self.base_url = self.base_url.strip()
        self.endpoint_path = self.endpoint_path.strip()
        self.auth_style = self.auth_style.strip()
        self.ai_connection_status = self.ai_connection_status.strip().lower() or "unknown"
        self.ai_connection_message = self.ai_connection_message.strip()
        self.ai_connection_checked_at = self.ai_connection_checked_at.strip()
        if self.ai_connection_status not in {"unknown", "connected", "check_settings"}:
            self.ai_connection_status = "unknown"
        preset = PROVIDER_PRESETS.get(self.provider)
        if preset:
            self.api_format = self.api_format or preset.api_format
            self.base_url = self.base_url or preset.base_url
            self.endpoint_path = self.endpoint_path or preset.endpoint_path
            self.auth_style = self.auth_style or preset.auth_style
            if preset.managed_model:
                self.model = preset.default_model

    @property
    def ai_configured(self) -> bool:
        if not self.provider or not self.api_key:
            return False
        try:
            self.resolved_provider()
        except ValidationError:
            return False
        return True

    def resolved_provider(self):
        return resolve_provider_config(
            provider=self.provider,
            api_key=self.api_key,
            model=self.model,
            api_format=self.api_format,
            base_url=self.base_url,
            endpoint_path=self.endpoint_path,
            auth_style=self.auth_style,
        )

    @property
    def search_configured(self) -> bool:
        return self.search_engine in SEARCH_ENGINES or bool(self.mcp_command or self.mcp_http_url)

    @property
    def completed(self) -> bool:
        return self.ai_configured

    def public_dict(self) -> dict[str, Any]:
        key_hint = mask_secret(self.api_key)
        search_hint = mask_secret(self.search_api_key)
        return {
            "provider": self.provider,
            "model": self.model,
            "api_format": self.api_format,
            "base_url": self.base_url,
            "endpoint_path": self.endpoint_path,
            "auth_style": self.auth_style,
            "search_engine": self.search_engine,
            "mcp_transport": self.mcp_transport,
            "mcp_command": self.mcp_command,
            "mcp_http_url": self.mcp_http_url,
            "mcp_tool_name": self.mcp_tool_name,
            "mcp_headers": "",
            "mcp_headers_hint": mask_json_headers(self.mcp_headers),
            "configured_at": self.configured_at,
            "configured": self.completed,
            "ai_configured": self.ai_configured,
            "ai_connection_status": self.ai_connection_status,
            "ai_connection_message": self.ai_connection_message,
            "ai_connection_checked_at": self.ai_connection_checked_at,
            "search_configured": self.search_configured,
            "api_key_hint": key_hint,
            "search_api_key_hint": search_hint,
        }


class GatewayStore:
    def __init__(self, path: Path | str = "data/gateway.json"):
        self.path = Path(path).expanduser()

    def load(self) -> GatewayConfig:
        if not self.path.exists():
            return GatewayConfig()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValidationError(f"could not read gateway configuration: {error}") from error
        allowed = set(GatewayConfig.__dataclass_fields__)
        values = {key: payload.get(key, "") for key in allowed}
        values.pop("api_key", None)
        values.pop("search_api_key", None)
        values["api_key"] = str(payload.get("api_key", ""))
        values["search_api_key"] = str(payload.get("search_api_key", ""))
        return GatewayConfig(**values)

    def save(self, config: GatewayConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n"
        temp = self.path.with_suffix(".tmp")
        try:
            temp.write_text(payload, encoding="utf-8")
            os.chmod(temp, 0o600)
            os.replace(temp, self.path)
            os.chmod(self.path, 0o600)
        except OSError as error:
            temp.unlink(missing_ok=True)
            raise ValidationError(f"could not write gateway configuration: {error}") from error


class ProviderGateway:
    def __init__(self, config: GatewayConfig, timeout_seconds: int = 60):
        self.config = config
        self.timeout_seconds = timeout_seconds

    def test_connection(self) -> dict[str, Any]:
        self._require_ai()
        text = self._request("Reply with the word connected.")
        return {"ok": True, "message": text[:120] or "connected"}

    def discover_formula(
        self,
        query: str,
        library: list[dict[str, Any]],
    ) -> FormulaDiscovery:
        self._require_ai()
        raw = self._request(
            FORMULA_DISCOVERY_SKILL,
            build_formula_discovery_prompt(query, library),
            json_schema=FORMULA_DISCOVERY_SCHEMA,
        )
        return parse_formula_discovery(raw)

    def discover_formula_candidates(
        self,
        query: str,
        library: list[dict[str, Any]],
    ) -> list[FormulaCandidate]:
        self._require_ai()
        raw = self._request(
            FORMULA_CANDIDATE_SKILL,
            build_formula_candidate_prompt(query, library),
            json_schema=FORMULA_CANDIDATE_SCHEMA,
        )
        return parse_formula_candidates(raw)

    def synthesize(
        self,
        query: str,
        sources: list[SearchResult],
        map_context: dict[str, Any] | None = None,
    ) -> SynthesisResult:
        self._require_ai()
        source_payload = [
            {"title": s.title, "url": s.url, "publisher": s.publisher, "excerpt": s.excerpt}
            for s in sources
        ]
        system = build_formula_synthesis_prompt(has_sources=bool(source_payload))
        prompt = json.dumps({
            "formula_request": query,
            "sources": source_payload,
            "active_map": map_context or {
                "session_id": "",
                "formula_ids": [],
                "formulas": [],
                "relationships": [],
            },
            "mode": "provider_native_answer" if not source_payload else "source_bounded_answer",
            "output": {
                "name": "string", "latex": "string", "aliases": ["string"], "topic_tags": ["string"],
                "ai_module": {"summary": "string", "explanation": "string", "examples": ["string"], "derivation_steps": ["string"]},
                "sources": [{"title": "string", "url": "string", "publisher": "string", "excerpt": "string"}],
                "dependencies": [{"prerequisite_name": "string", "local_formula_id": "string", "relation": "prerequisite|derivation_basis|special_case|generalization|equivalent_form", "rationale": "string", "confidence": 0.0, "source_urls": ["string"]}],
                "warnings": ["string"],
            },
            "response_schema": SYNTHESIS_SCHEMA,
        }, ensure_ascii=False)
        raw = self._request(system, prompt, json_schema=SYNTHESIS_SCHEMA)
        return parse_synthesis_result(_extract_json(raw))

    def deep_dive(
        self,
        formula: dict[str, Any],
        sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self._require_ai()
        raw = self._request(
            f"{FORMULA_DEEP_DIVE_SKILL}\n\n{load_agent_skill('formula_deep_dive')}",
            build_formula_deep_dive_prompt(formula, sources),
            json_schema=FORMULA_DEEP_DIVE_SCHEMA,
        )
        return parse_formula_deep_dive(_extract_json(raw))

    def deep_dive_relationship(
        self,
        relationship: dict[str, Any],
        sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self._require_ai()
        raw = self._request(
            f"{RELATIONSHIP_DEEP_DIVE_SKILL}\n\n{load_agent_skill('relationship_deep_dive')}",
            build_relationship_deep_dive_prompt(relationship, sources),
            json_schema=FORMULA_DEEP_DIVE_SCHEMA,
        )
        return parse_formula_deep_dive(_extract_json(raw))

    def validate_relationship(
        self,
        relationship: dict[str, Any],
        sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self._require_ai()
        raw = self._request(
            f"{RELATIONSHIP_VALIDATION_SKILL}\n\n{load_agent_skill('relationship_deep_dive')}",
            build_relationship_validation_prompt(relationship, sources),
            json_schema=RELATIONSHIP_VALIDATION_SCHEMA,
        )
        return parse_relationship_validation(_extract_json(raw))

    def introduce(
        self,
        formula: dict[str, Any],
        sources: list[dict[str, Any]],
    ) -> str:
        self._require_ai()
        raw = self._request(
            f"{FORMULA_INTRODUCTION_SKILL}\n\n{load_agent_skill('formula_introduction')}",
            build_formula_introduction_prompt(formula, sources),
            json_schema=FORMULA_INTRODUCTION_SCHEMA,
        )
        return parse_formula_introduction(_extract_json(raw))

    def chat(
        self,
        formula: dict[str, Any],
        deep_dive: dict[str, Any],
        messages: list[dict[str, str]],
    ) -> str:
        self._require_ai()
        return self._request(
            f"{FORMULA_CHAT_SKILL}\n\n{load_agent_skill('formula_deep_dive')}",
            build_formula_chat_prompt(formula, deep_dive, messages),
        ).strip()

    def _require_ai(self) -> None:
        if not self.config.ai_configured:
            raise SynthesisError("AI provider is not configured")

    def _request(
        self,
        system: str,
        user: str = "",
        json_schema: dict[str, Any] | None = None,
    ) -> str:
        if json_schema is not None:
            system = (
                f"{system}\n"
                "Required JSON schema:\n"
                f"{json.dumps(json_schema, ensure_ascii=False, separators=(',', ':'))}"
            )
        adapter = adapter_for_config(
            self.config.resolved_provider(),
            timeout_seconds=self.timeout_seconds,
        )
        resolved = self.config.resolved_provider()
        response = adapter.complete(
            ProviderRequest(
                model=resolved.model,
                api_key=resolved.api_key,
                system_prompt=system,
                user_prompt=user,
                json_schema=json_schema,
            )
        )
        return response.text


class SearchGateway:
    def __init__(self, config: GatewayConfig, timeout_seconds: int = 30):
        self.config = config
        self.timeout_seconds = timeout_seconds

    def provider(self) -> SearchProvider | None:
        if self.config.mcp_command or self.config.mcp_http_url:
            if self.config.mcp_http_url:
                return MCPHTTPClient(self.config.mcp_http_url, self.config.mcp_tool_name, self.config.mcp_headers, self.timeout_seconds)
            return MCPStdioClient(tuple(shlex.split(self.config.mcp_command)), self.config.mcp_tool_name, self.timeout_seconds)
        return None

    def test_connection(self) -> dict[str, Any]:
        provider = self.provider()
        if provider is None:
            return {"ok": True, "result_count": 0, "engine": "provider-native"}
        try:
            if hasattr(provider, "__enter__"):
                with provider as entered:
                    results = entered.search("mathematics", limit=1)
            else:
                results = provider.search("mathematics", limit=1)
        except (RetrievalError, OSError, ValueError) as error:
            raise RetrievalError(f"search connection failed: {error}") from error
        return {"ok": True, "result_count": len(results), "engine": self.config.search_engine or "mcp"}


class EngineSearchProvider:
    def __init__(self, config: GatewayConfig, timeout_seconds: int = 30):
        self.config = config
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        engine = self.config.search_engine
        if engine == "google":
            return self._google(query, limit)
        if engine == "bing":
            return self._bing(query, limit)
        if engine == "yahoo":
            return self._yahoo(query, limit)
        if engine == "baidu":
            return self._baidu(query, limit)
        raise RetrievalError("search engine is not configured")

    def _google(self, query: str, limit: int) -> list[SearchResult]:
        if not self.config.search_api_key or not self.config.search_engine_id:
            raise RetrievalError("Google search requires a search API key and engine ID")
        params = urllib.parse.urlencode({"key": self.config.search_api_key, "cx": self.config.search_engine_id, "q": query, "num": limit})
        return _json_search(f"https://www.googleapis.com/customsearch/v1?{params}", "items", self.timeout_seconds)

    def _bing(self, query: str, limit: int) -> list[SearchResult]:
        if not self.config.search_api_key:
            raise RetrievalError("Bing search requires a search API key")
        request = urllib.request.Request(
            "https://api.bing.microsoft.com/v7.0/search?" + urllib.parse.urlencode({"q": query, "count": limit}),
            headers={"Ocp-Apim-Subscription-Key": self.config.search_api_key},
        )
        return _json_search_request(request, "webPages", self.timeout_seconds)

    def _yahoo(self, query: str, limit: int) -> list[SearchResult]:
        if not self.config.search_api_key:
            raise RetrievalError("Yahoo search requires a search API key")
        params = urllib.parse.urlencode({"appid": self.config.search_api_key, "query": query, "count": limit})
        return _json_search(f"https://boss.yahooapis.com/ysearch/web/v1/results?{params}", "results", self.timeout_seconds)

    def _baidu(self, query: str, limit: int) -> list[SearchResult]:
        params = urllib.parse.urlencode({"wd": query, "rn": limit})
        request = urllib.request.Request(f"https://www.baidu.com/s?{params}", headers={"User-Agent": "Mozilla/5.0"})
        try:
            with open_url(request, timeout=self.timeout_seconds) as response:
                html = response.read().decode("utf-8", "ignore")
        except (urllib.error.URLError, OSError) as error:
            raise RetrievalError(f"Baidu search request failed: {error}") from error
        import re
        matches = re.findall(r'<h3[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?</h3>', html, re.S | re.I)
        results = []
        for url, title in matches[:limit]:
            clean = re.sub(r"<[^>]+>", "", title).strip()
            if clean and url.startswith("http"):
                results.append(SearchResult(clean, url, "Baidu", f"Search result for {query}", datetime.now(timezone.utc).replace(microsecond=0).isoformat()))
        return results


def mask_secret(value: str) -> str:
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return value[:3] + "…" + value[-2:]


def mask_json_headers(value: str) -> str:
    if not value:
        return ""
    try:
        headers = json.loads(value)
    except json.JSONDecodeError:
        return "Saved headers"
    if not isinstance(headers, dict):
        return "Saved headers"
    return ", ".join(str(key) for key in headers)


def _json_search(url: str, key: str, timeout: int) -> list[SearchResult]:
    return _json_search_request(urllib.request.Request(url), key, timeout)


def _json_search_request(request: urllib.request.Request, key: str, timeout: int) -> list[SearchResult]:
    try:
        with open_url(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
        raise RetrievalError(f"search request failed: {error}") from error
    raw = payload.get(key)
    if isinstance(raw, dict):
        raw = raw.get("value", raw.get("results", []))
    return parse_search_results(raw or [])


_extract_provider_text = extract_provider_text


def _extract_json(raw: str) -> str:
    raw = raw.strip()
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            return raw[start : end + 1]
        raise SynthesisError("AI provider returned invalid JSON")


SYNTHESIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "latex", "aliases", "topic_tags", "ai_module", "sources", "dependencies", "warnings"],
    "properties": {
        "name": {"type": "string"},
        "latex": {"type": "string"},
        "aliases": {"type": "array", "items": {"type": "string"}},
        "topic_tags": {"type": "array", "items": {"type": "string"}},
        "ai_module": {
            "type": "object",
            "additionalProperties": False,
            "required": ["summary", "explanation", "examples", "derivation_steps"],
            "properties": {
                "summary": {"type": "string"},
                "explanation": {"type": "string"},
                "examples": {"type": "array", "items": {"type": "string"}},
                "derivation_steps": {"type": "array", "items": {"type": "string"}},
            },
        },
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "url", "publisher", "excerpt"],
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "publisher": {"type": "string"},
                    "excerpt": {"type": "string"},
                },
            },
        },
        "dependencies": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["prerequisite_name", "local_formula_id", "relation", "rationale", "confidence", "source_urls"],
                "properties": {
                    "prerequisite_name": {"type": "string"},
                    "local_formula_id": {"type": "string"},
                    "relation": {"type": "string", "enum": ["prerequisite", "derivation_basis", "special_case", "generalization", "equivalent_form"]},
                    "rationale": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "source_urls": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}
