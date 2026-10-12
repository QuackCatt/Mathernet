from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from .errors import SynthesisError
from .models import AIModule, EdgeRelation
from .retrieval import SearchResult


@dataclass(slots=True)
class SynthesisDependency:
    prerequisite_name: str
    relation: EdgeRelation
    rationale: str
    source_urls: list[str]


@dataclass(slots=True)
class SynthesisResult:
    name: str
    latex: str
    aliases: list[str]
    topic_tags: list[str]
    ai_module: AIModule
    dependencies: list[SynthesisDependency] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Synthesizer(Protocol):
    def synthesize(self, query: str, sources: list[SearchResult]) -> SynthesisResult: ...


class RuleBasedSynthesizer:
    """Offline-safe synthesizer that never invents relations or derivations."""

    def synthesize(self, query: str, sources: list[SearchResult]) -> SynthesisResult:
        if not sources:
            raise SynthesisError("at least one reliable source is required")
        source_titles = ", ".join(source.title for source in sources)
        return SynthesisResult(
            name=query,
            latex=query if "=" in query else r"\text{" + query.replace("}", "") + "}",
            aliases=[],
            topic_tags=["mathematics"],
            ai_module=AIModule(
                summary=f"Source-backed overview of {query}.",
                explanation=(
                    f"Mathernet found {len(sources)} reliable source(s): {source_titles}. "
                    "This offline record preserves their excerpts without adding an unsupported derivation."
                ),
                examples=[],
                derivation_steps=[],
            ),
            dependencies=[],
            warnings=["Offline synthesis does not propose dependency edges."],
        )


class OpenAIResponsesSynthesizer:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5-mini",
        timeout_seconds: int = 60,
        endpoint: str = "https://api.openai.com/v1/responses",
    ):
        if not api_key:
            raise SynthesisError("OPENAI_API_KEY is not configured")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.endpoint = endpoint

    def synthesize(self, query: str, sources: list[SearchResult]) -> SynthesisResult:
        if not sources:
            raise SynthesisError("at least one reliable source is required")
        source_payload = [
            {
                "title": source.title,
                "url": source.url,
                "publisher": source.publisher,
                "excerpt": source.excerpt,
            }
            for source in sources
        ]
        system_prompt = (
            "You are Mathernet, a study-only formula learning assistant. "
            "Use only the supplied source material. Never invent a formula, derivation, source, or dependency. "
            "Propose a dependency only when the supplied material supports it, and cite only supplied URLs. "
            "Do not solve exams or homework. Return only valid JSON matching the requested schema."
        )
        user_prompt = json.dumps(
            {
                "formula_request": query,
                "sources": source_payload,
                "instructions": [
                    "Create a plain-language formula card.",
                    "Store canonical mathematics in latex.",
                    "Keep every dependency directed from a prerequisite formula to the requested formula.",
                    "Use relation values: prerequisite, derivation_basis, special_case, generalization, equivalent_form.",
                ],
            },
            ensure_ascii=False,
        )
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "latex", "aliases", "topic_tags", "ai_module", "dependencies", "warnings"],
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
                "dependencies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["prerequisite_name", "relation", "rationale", "source_urls"],
                        "properties": {
                            "prerequisite_name": {"type": "string"},
                            "relation": {"type": "string", "enum": [item.value for item in EdgeRelation]},
                            "rationale": {"type": "string"},
                            "source_urls": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "warnings": {"type": "array", "items": {"type": "string"}},
            },
        }
        request_body = {
            "model": self.model,
            "instructions": system_prompt,
            "input": user_prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "mathernet_formula_card",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
            raise SynthesisError(f"language model request failed: {error}") from error
        return parse_synthesis_result(extract_response_text(payload))


def extract_response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str) and payload["output_text"]:
        return payload["output_text"]
    chunks: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        content = item.get("content", [])
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    if not chunks:
        raise SynthesisError("language model response did not contain output text")
    return "".join(chunks)


def parse_synthesis_result(raw: str) -> SynthesisResult:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SynthesisError(f"language model returned invalid JSON: {error}") from error
    try:
        ai_data = data["ai_module"]
        dependencies = [
            SynthesisDependency(
                prerequisite_name=str(item["prerequisite_name"]),
                relation=EdgeRelation(item["relation"]),
                rationale=str(item["rationale"]),
                source_urls=[str(url) for url in item["source_urls"]],
            )
            for item in data.get("dependencies", [])
        ]
        return SynthesisResult(
            name=str(data["name"]),
            latex=str(data["latex"]),
            aliases=[str(item) for item in data.get("aliases", [])],
            topic_tags=[str(item) for item in data.get("topic_tags", [])],
            ai_module=AIModule(
                summary=str(ai_data["summary"]),
                explanation=str(ai_data["explanation"]),
                examples=[str(item) for item in ai_data.get("examples", [])],
                derivation_steps=[str(item) for item in ai_data.get("derivation_steps", [])],
            ),
            dependencies=dependencies,
            warnings=[str(item) for item in data.get("warnings", [])],
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SynthesisError(f"language model JSON is missing required fields: {error}") from error
