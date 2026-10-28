from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from .errors import SynthesisError
from .models import AIModule, EdgeRelation, SearchResult


@dataclass(slots=True)
class SynthesisDependency:
    prerequisite_name: str
    relation: EdgeRelation
    rationale: str
    source_urls: list[str]
    local_formula_id: str = ""
    confidence: float = 0.0


@dataclass(slots=True)
class SynthesisResult:
    name: str
    latex: str
    aliases: list[str]
    topic_tags: list[str]
    ai_module: AIModule
    sources: list[SearchResult] = field(default_factory=list)
    dependencies: list[SynthesisDependency] = field(default_factory=list)


class Synthesizer(Protocol):
    def synthesize(
        self,
        query: str,
        sources: list[SearchResult],
        map_context: dict[str, Any] | None = None,
    ) -> SynthesisResult: ...


def parse_synthesis_result(raw: str) -> SynthesisResult:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SynthesisError(f"language model returned invalid JSON: {error}") from error
    data = _normalize_synthesis_payload(data)
    try:
        ai_data = data["ai_module"]
        summary = (
            str(ai_data.get("summary") or "").strip()
            if isinstance(ai_data, dict)
            else str(ai_data or "").strip()
        )
        if not summary:
            raise KeyError("ai_module.summary")
        dependencies = [
            SynthesisDependency(
                prerequisite_name=str(
                    item.get("prerequisite_name")
                    or item.get("local_formula_name")
                    or item.get("local_formula_id")
                ),
                relation=EdgeRelation(item["relation"]),
                rationale=str(item["rationale"]),
                source_urls=[str(url) for url in item.get("source_urls", [])],
                local_formula_id=str(item.get("local_formula_id", "")),
                confidence=min(1.0, max(0.0, float(item.get("confidence", 0.0)))),
            )
            for item in data.get("dependencies", [])
        ]
        source_items = data.get("sources", [])
        sources = []
        for item in source_items if isinstance(source_items, list) else []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("name") or "").strip()
            url = str(item.get("url") or item.get("link") or "").strip()
            publisher = str(item.get("publisher") or item.get("source") or "AI citation").strip()
            excerpt = str(item.get("excerpt") or item.get("snippet") or item.get("description") or "").strip()
            if title and url:
                sources.append(SearchResult(title, url, publisher or "AI citation", excerpt or "AI citation"))
        return SynthesisResult(
            name=str(data["name"]),
            latex=str(data["latex"]),
            aliases=_string_values(data.get("aliases", [])),
            topic_tags=_string_values(data.get("topic_tags", [])),
            ai_module=AIModule(summary=summary),
            sources=sources,
            dependencies=dependencies,
        )
    except (KeyError, TypeError, ValueError) as error:
        fields = ", ".join(sorted(data.keys())) if isinstance(data, dict) else type(data).__name__
        raise SynthesisError(
            f"language model JSON is missing required fields: {error}; received fields: {fields}"
        ) from error


def _normalize_synthesis_payload(data: Any) -> dict[str, Any]:
    current = data
    for _ in range(5):
        if not isinstance(current, dict):
            break
        if any(key in current for key in ("ai_module", "aiModule", "summary", "explanation")):
            break
        nested = next(
            (
                current[key]
                for key in ("result", "data", "formula_card", "formulaCard", "formula", "card", "output", "json", "response")
                if isinstance(current.get(key), dict)
            ),
            None,
        )
        if nested is None:
            break
        current = nested
    if not isinstance(current, dict):
        raise SynthesisError("language model JSON did not contain a formula object")

    aliases = {
        "formula_name": "name",
        "formulaName": "name",
        "title": "name",
        "formula": "latex",
        "expression": "latex",
        "formula_latex": "latex",
        "formulaLatex": "latex",
        "topic_tags": "topic_tags",
        "topicTags": "topic_tags",
        "ai_module": "ai_module",
        "aiModule": "ai_module",
        "source_urls": "source_urls",
        "sourceUrls": "source_urls",
        "prerequisite_name": "prerequisite_name",
        "prerequisiteName": "prerequisite_name",
        "local_formula_id": "local_formula_id",
        "localFormulaId": "local_formula_id",
        "local_formula_name": "local_formula_name",
        "localFormulaName": "local_formula_name",
    }
    normalized = {aliases.get(key, key): value for key, value in current.items()}
    if "ai_module" not in normalized:
        if "summary" in normalized or "explanation" in normalized:
            normalized["ai_module"] = {
                "summary": normalized.get("summary") or normalized.get("explanation", ""),
            }
    ai_module = normalized.get("ai_module")
    if isinstance(ai_module, str):
        normalized["ai_module"] = {"summary": ai_module}
    elif isinstance(ai_module, dict):
        normalized["ai_module"] = {
            "summary": ai_module.get("summary") or ai_module.get("explanation", ""),
        }

    dependencies = normalized.get("dependencies", [])
    if isinstance(dependencies, dict):
        dependencies = list(dependencies.values())
    normalized["dependencies"] = [
        {aliases.get(key, key): value for key, value in item.items()}
        for item in dependencies
        if isinstance(item, dict)
    ]
    sources = normalized.get("sources", [])
    if isinstance(sources, dict):
        sources = list(sources.values())
    normalized["sources"] = sources
    return normalized


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]
