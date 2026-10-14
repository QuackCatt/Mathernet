from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from .errors import SynthesisError


FORMULA_DISCOVERY_SKILL = (
    "You are Mathernet's formula discovery skill. Resolve the request to one canonical mathematical "
    "formula or concept. Use the model's built-in web search when available to identify the accepted "
    "name, aliases, and expression. Then compare that result with the supplied local formula catalog. "
    "Return local_formula_id only when the request refers to the same formula, not a related or "
    "prerequisite formula. Never create a duplicate match from a similar topic alone. Do not solve "
    "exams or homework. Return only valid JSON matching the requested schema."
)

FORMULA_SYNTHESIS_SKILL = (
    "You are Mathernet, a study-only formula learning assistant. Use the model's built-in web search "
    "when available and no source material is supplied. When source material is supplied, treat it as "
    "the factual boundary. Never invent a citation, URL, formula, derivation, or dependency. If web "
    "results are unavailable, give a carefully qualified answer and return an empty sources list. "
    "Return only valid JSON matching the requested schema. Do not solve exams or homework."
)

DEDUPLICATION_SKILL = (
    "Prefer opening an existing formula card over creating another card. Match by canonical name, "
    "LaTeX expression, accepted alias, or explicit discovery result. Related formulas do not count as "
    "duplicates. When a duplicate is found, return it unchanged and do not create new source or edge "
    "records for the rejected creation attempt."
)

FORMULA_DEEP_DIVE_SKILL = (
    "Read and follow the local formula deep-dive skill instructions before generating. Return only "
    "valid JSON matching the requested schema."
)

FORMULA_CHAT_SKILL = (
    "Continue the study conversation using the same formula deep-dive skill instructions. Be direct, "
    "acknowledge uncertainty, use LaTeX for mathematics, and never invent citations or source URLs."
)

FORMULA_INTRODUCTION_SKILL = (
    "Read and follow the local formula introduction skill instructions before generating. Return only "
    "valid JSON matching the requested schema."
)

FORMULA_DISCOVERY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["canonical_name", "local_formula_id", "aliases", "confidence", "reason"],
    "properties": {
        "canonical_name": {"type": "string"},
        "local_formula_id": {"type": "string"},
        "aliases": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
}

FORMULA_DEEP_DIVE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "introduction", "sections", "sources", "warnings"],
    "properties": {
        "title": {"type": "string"},
        "introduction": {"type": "string"},
        "sections": {"type": "array", "items": {"$ref": "#/$defs/article_section"}},
        "sources": {"type": "array", "items": {"$ref": "#/$defs/source_item"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "$defs": {
        "article_section": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "subtitle", "heading", "body"],
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["story", "application", "background", "context", "other"],
                },
                "subtitle": {"type": "string"},
                "heading": {"type": "string"},
                "body": {"type": "string"},
            },
        },
        "source_item": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "url", "publisher"],
            "properties": {
                "title": {"type": "string"},
                "url": {"type": "string"},
                "publisher": {"type": "string"},
            },
        },
    },
}

FORMULA_INTRODUCTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["introduction"],
    "properties": {
        "introduction": {"type": "string"},
    },
}


@dataclass(slots=True)
class FormulaDiscovery:
    canonical_name: str
    local_formula_id: str = ""
    aliases: list[str] | None = None
    confidence: float = 0.0
    reason: str = ""

    def __post_init__(self) -> None:
        self.canonical_name = self.canonical_name.strip()
        self.local_formula_id = self.local_formula_id.strip()
        self.aliases = [alias.strip() for alias in (self.aliases or []) if alias.strip()]
        self.confidence = min(1.0, max(0.0, float(self.confidence)))
        self.reason = self.reason.strip()


def build_formula_discovery_prompt(
    query: str,
    library: Iterable[dict[str, Any]],
) -> str:
    catalog = [
        {
            "id": str(item.get("id", "")),
            "name": str(item.get("name", "")),
            "aliases": [str(alias) for alias in item.get("aliases", [])],
            "latex": str(item.get("latex", "")),
        }
        for item in library
    ]
    return json.dumps(
        {
            "request": query,
            "local_formula_catalog": catalog,
            "task": "Resolve the request, use web search when available, then identify an exact local match.",
            "deduplication_policy": DEDUPLICATION_SKILL,
        },
        ensure_ascii=False,
    )


def parse_formula_discovery(raw: str) -> FormulaDiscovery:
    data = _json_object(raw)
    aliases = data.get("aliases", [])
    if not isinstance(aliases, list):
        aliases = []
    try:
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    return FormulaDiscovery(
        canonical_name=str(data.get("canonical_name", "")),
        local_formula_id=str(data.get("local_formula_id", "")),
        aliases=[str(alias) for alias in aliases],
        confidence=confidence,
        reason=str(data.get("reason", "")),
    )


def build_formula_synthesis_prompt(*, has_sources: bool) -> str:
    mode = "source_bounded_answer" if has_sources else "provider_native_answer"
    return f"{FORMULA_SYNTHESIS_SKILL}\nCurrent mode: {mode}."


def build_formula_deep_dive_prompt(
    formula: dict[str, Any],
    sources: Iterable[dict[str, Any]],
) -> str:
    return json.dumps(
        {
            "skill_file": "mathernet/skills/formula_deep_dive.md",
            "formula": formula,
            "known_sources": list(sources),
            "task": (
                "Generate the session's initial long-form article. Include only optional topics that "
                "are genuinely useful, and include only real source URLs at the end."
            ),
        },
        ensure_ascii=False,
    )


def parse_formula_deep_dive(raw: str) -> dict[str, Any]:
    data = _json_object(raw)
    introduction = _text(data.get("introduction"))
    sections = _article_sections(data.get("sections"))
    if not introduction and not sections:
        raise SynthesisError("AI deep-dive response did not contain an article")
    return {
        "title": _text(data.get("title")) or "Deep dive",
        "article": {
            "introduction": introduction,
            "sections": sections,
        },
        "sources": _source_items(data.get("sources")),
        "warnings": _text_list(data.get("warnings")),
    }


def build_formula_introduction_prompt(
    formula: dict[str, Any],
    sources: Iterable[dict[str, Any]],
) -> str:
    return json.dumps(
        {
            "skill_file": "mathernet/skills/formula_introduction.md",
            "formula": formula,
            "known_sources": list(sources),
            "task": (
                "Generate one 110-150 word introduction covering the formula's definition, meaning, "
                "typical use, and importance."
            ),
        },
        ensure_ascii=False,
    )


def parse_formula_introduction(raw: str) -> str:
    data = _json_object(raw)
    introduction = _text(data.get("introduction"))
    if not introduction:
        raise SynthesisError("AI formula introduction response did not contain an introduction")
    word_count = len(re.findall(r"\b[\w'-]+\b", introduction))
    if word_count < 100 or word_count > 180:
        raise SynthesisError(
            f"AI formula introduction must contain 100-180 words; received {word_count}"
        )
    return introduction


def build_formula_chat_prompt(
    formula: dict[str, Any],
    deep_dive: dict[str, Any],
    messages: Iterable[dict[str, str]],
) -> str:
    return json.dumps(
        {
            "skill_file": "mathernet/skills/formula_deep_dive.md",
            "formula": formula,
            "deep_dive": deep_dive,
            "conversation": [
                {"role": str(item.get("role", "")), "content": str(item.get("content", ""))}
                for item in messages
            ],
        },
        ensure_ascii=False,
    )


@lru_cache(maxsize=8)
def load_agent_skill(name: str) -> str:
    path = Path(__file__).with_name("skills") / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SynthesisError(f"could not read agent skill {path}: {error}") from error
    if not text.strip():
        raise SynthesisError(f"agent skill {path} is empty")
    return text


def _text(value: Any) -> str:
    return str(value or "").strip()


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _text(item))][:20]


def _article_sections(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    allowed = {"story", "application", "background", "context", "other"}
    sections = []
    for item in value[:12]:
        if not isinstance(item, dict):
            continue
        kind = _text(item.get("kind")).lower()
        subtitle = _text(item.get("subtitle"))
        heading = _text(item.get("heading"))
        body = _text(item.get("body"))
        if kind in allowed and subtitle and heading and body:
            sections.append({
                "kind": kind,
                "subtitle": subtitle[:160],
                "heading": heading[:240],
                "body": body[:8_000],
            })
    return sections


def _source_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value[:10]:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title"))
        url = _text(item.get("url"))
        publisher = _text(item.get("publisher"))
        parsed = urlparse(url)
        if title and publisher and parsed.scheme in {"http", "https"} and parsed.netloc:
            items.append({"title": title[:300], "url": url, "publisher": publisher[:120]})
    return items


def _json_object(raw: str) -> dict[str, Any]:
    candidate = raw.strip()
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise SynthesisError("AI discovery returned invalid JSON")
        try:
            data = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as error:
            raise SynthesisError("AI discovery returned invalid JSON") from error
    if not isinstance(data, dict):
        raise SynthesisError("AI discovery did not return an object")
    return data
