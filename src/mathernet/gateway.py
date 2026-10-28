from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .agent_skills import (
    AI_SAFETY_POLICY,
    CHAT_SAFETY_REVIEW_SCHEMA,
    CHAT_SAFETY_REVIEW_SKILL,
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
    FormulaCandidate,
    FormulaDiscovery,
    ChatSafetyReview,
    build_chat_safety_review_prompt,
    build_formula_candidate_prompt,
    build_formula_chat_prompt,
    build_formula_deep_dive_prompt,
    build_formula_discovery_prompt,
    build_formula_introduction_prompt,
    build_formula_synthesis_prompt,
    build_relationship_deep_dive_prompt,
    build_relationship_validation_prompt,
    load_agent_skill,
    parse_chat_safety_review,
    parse_formula_candidates,
    parse_formula_deep_dive,
    parse_formula_discovery,
    parse_formula_introduction,
    parse_relationship_validation,
)
from .errors import SynthesisError, ValidationError
from .fsutil import chmod_private
from .llm import SynthesisResult, parse_synthesis_result
from .models import SearchResult
from .providers import (
    PROVIDER_PRESETS,
    ProviderRequest,
    adapter_for_config,
    resolve_provider_config,
)


@dataclass(slots=True)
class GatewayConfig:
    provider: str = ""
    api_key: str = ""
    model: str = ""
    api_format: str = ""
    base_url: str = ""
    endpoint_path: str = ""
    auth_style: str = ""
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
    def completed(self) -> bool:
        return self.ai_configured

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "api_format": self.api_format,
            "base_url": self.base_url,
            "endpoint_path": self.endpoint_path,
            "auth_style": self.auth_style,
            "configured_at": self.configured_at,
            "configured": self.completed,
            "ai_configured": self.ai_configured,
            "ai_connection_status": self.ai_connection_status,
            "ai_connection_message": self.ai_connection_message,
            "ai_connection_checked_at": self.ai_connection_checked_at,
            "api_key_hint": mask_secret(self.api_key),
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
        if not isinstance(payload, dict):
            raise ValidationError("gateway configuration must be a JSON object")
        allowed = set(GatewayConfig.__dataclass_fields__)
        values = {key: str(payload.get(key) or "") for key in allowed}
        values.pop("api_key", None)
        values["api_key"] = str(payload.get("api_key") or "")
        return GatewayConfig(**values)

    def save(self, config: GatewayConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n"
        temp = self.path.with_suffix(".tmp")
        try:
            temp.write_text(payload, encoding="utf-8")
            chmod_private(temp)
            os.replace(temp, self.path)
            chmod_private(self.path)
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
        context = dict(map_context or {})
        selected_candidate = context.pop("selected_candidate", None)
        prompt = json.dumps({
            "formula_request": query,
            "selected_candidate": selected_candidate,
            "sources": source_payload,
            "active_map": context or {
                "session_id": "",
                "formula_ids": [],
                "formulas": [],
                "relationships": [],
            },
            "mode": "provider_native_answer" if not source_payload else "source_bounded_answer",
            "output": {
                "name": "string", "latex": "string", "aliases": ["string"], "topic_tags": ["string"],
                "ai_module": {"summary": "string"},
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

    def review_chat_response(
        self,
        formula: dict[str, Any],
        deep_dive: dict[str, Any],
        message: str,
        reply: str,
    ) -> ChatSafetyReview:
        self._require_ai()
        raw = self._request(
            CHAT_SAFETY_REVIEW_SKILL,
            build_chat_safety_review_prompt(formula, deep_dive, message, reply),
            json_schema=CHAT_SAFETY_REVIEW_SCHEMA,
            temperature=0.0,
        )
        return parse_chat_safety_review(_extract_json(raw))

    def _require_ai(self) -> None:
        if not self.config.ai_configured:
            raise SynthesisError("AI provider is not configured")

    def _request(
        self,
        system: str,
        user: str = "",
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.1,
    ) -> str:
        system = f"{AI_SAFETY_POLICY}\n\n{system}"
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
                temperature=temperature,
            )
        )
        return response.text


def mask_secret(value: str) -> str:
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return value[:3] + "…" + value[-2:]


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
            "required": ["summary"],
            "properties": {
                "summary": {"type": "string"},
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
