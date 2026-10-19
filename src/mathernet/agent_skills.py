from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from .errors import SynthesisError
from .normalization import formula_key


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
    "the factual boundary for factual claims. You may infer relationships between mathematical "
    "objects from their definitions and notation even without citations. Never invent a citation or "
    "URL. If web results are unavailable, give a carefully qualified answer and return an empty "
    "sources list. Return only valid JSON matching the requested schema. Do not solve exams or homework."
)

FORMULA_RELATIONSHIP_SKILL = (
    "Relationship discovery is a required graph-building step. Compare the requested formula with "
    "EVERY formula in active_map.formulas before returning. Do not stop after finding one match. For "
    "each mathematically meaningful connection, emit one dependency using the exact local_formula_id "
    "from the catalog. Look deliberately for prerequisites, derivation bases, equivalent forms, "
    "special cases, and generalizations. Treat shared topic tags as weak evidence only; prefer "
    "symbolic or definitional links. Distributions especially require checking shared parameters, "
    "limiting cases, transformations, conjugacy, aggregation, conditional relationships, and named "
    "special cases. Include both directions of reasoning in rationale when useful, but keep the edge "
    "directional from the related formula to the new formula. Do not force a connection when only the "
    "broad field is shared. Confidence must reflect mathematical certainty, not stylistic confidence."
)

KNOWN_RELATIONSHIP_RULES = (
    ("pythagorean theorem", "distance formula", "derivation_basis",
     "The distance formula is the coordinate-plane form of the Pythagorean theorem."),
    ("power series", "euler's formula", "derivation_basis",
     "The exponential, sine, and cosine series combine to produce Euler's formula."),
    ("euler's formula", "euler's identity", "special_case",
     "Euler's identity is Euler's formula evaluated at x = pi."),
    ("taylor series", "exponential series", "special_case",
     "The exponential series is the Taylor series of the exponential function."),
    ("exponential series", "complex exponential", "derivation_basis",
     "Extending the exponential series to complex arguments defines the complex exponential."),
    ("derivative definition", "product rule", "derivation_basis",
     "The product rule follows by expanding the derivative definition for a product."),
    ("dot product", "cauchy-schwarz inequality", "derivation_basis",
     "The Cauchy-Schwarz inequality bounds the normalized dot product."),
    ("linear independence", "rank", "prerequisite",
     "Rank counts independent directions, so linear independence supplies its conceptual basis."),
    ("rank", "invertible matrix theorem", "prerequisite",
     "Full rank is one of the equivalent conditions in the invertible matrix theorem."),
    ("conditional probability", "bayes' theorem", "prerequisite",
     "Bayes' theorem rewrites an inverse conditional probability using conditional probability."),
    ("expectation", "variance", "prerequisite",
     "Variance is defined from expected squared deviation."),
    ("variance", "standard deviation", "special_case",
     "Standard deviation is the positive square root of variance."),
    ("least squares", "normal equation", "derivation_basis",
     "The normal equation is obtained by minimizing the least-squares objective."),
    ("discriminant", "quadratic formula", "prerequisite",
     "The discriminant determines the two roots given by the quadratic formula."),
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

RELATIONSHIP_DEEP_DIVE_SKILL = (
    "Read and follow the local relationship deep-dive skill instructions before generating. Explain "
    "why the two formulas are mathematically connected, using the saved relationship type. For a "
    "confirmed manual relationship, incorporate any learner_note as user-supplied context without "
    "treating it as unquestionable truth; omit learner_note when it is absent. Use LaTeX for "
    "mathematics, acknowledge uncertainty, and never invent citations."
)

RELATIONSHIP_VALIDATION_SKILL = (
    "You are Mathernet's relationship verification skill. Use the model's built-in web search when "
    "available. Judge the learner's explanation separately from external evidence. An empty, vague, "
    "incoherent, or mathematically incorrect explanation is not reasonable. Mark web_supported true "
    "only when real research sources specifically support the stated relationship between these two "
    "formulas. Never invent citations or URLs. Return only valid JSON matching the requested schema."
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

RELATIONSHIP_VALIDATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["explanation_is_reasonable", "web_supported", "assessment", "sources"],
    "properties": {
        "explanation_is_reasonable": {"type": "boolean"},
        "web_supported": {"type": "boolean"},
        "assessment": {"type": "string"},
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


@dataclass(slots=True)
class FormulaCandidate:
    canonical_name: str
    latex: str
    summary: str
    topic: str
    reason: str
    confidence: float = 0.0
    local_formula_id: str = ""

    def __post_init__(self) -> None:
        self.canonical_name = self.canonical_name.strip()
        self.latex = self.latex.strip()
        self.summary = self.summary.strip()
        self.topic = self.topic.strip()
        self.reason = self.reason.strip()
        self.local_formula_id = self.local_formula_id.strip()
        self.confidence = min(1.0, max(0.0, float(self.confidence)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "latex": self.latex,
            "summary": self.summary,
            "topic": self.topic,
            "reason": self.reason,
            "confidence": self.confidence,
            "local_formula_id": self.local_formula_id,
        }


FORMULA_CANDIDATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidates"],
    "properties": {
        "candidates": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "canonical_name",
                    "latex",
                    "summary",
                    "topic",
                    "reason",
                    "confidence",
                    "local_formula_id",
                ],
                "properties": {
                    "canonical_name": {"type": "string"},
                    "latex": {"type": "string"},
                    "summary": {"type": "string"},
                    "topic": {"type": "string"},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "local_formula_id": {"type": "string"},
                },
            },
        }
    },
}


FORMULA_CANDIDATE_SKILL = (
    "You are Mathernet's formula search skill. Interpret a possibly vague request and return one "
    "to five distinct formula candidates. Each candidate must be a concrete named mathematical "
    "formula, identity, theorem, distribution, or transform with a usable LaTeX expression. Do not "
    "return broad topics, duplicate equivalent names, or invented formulas. Use web search when "
    "available, prefer established mathematical references, and order candidates from most to least "
    "likely to match the request. Return only valid JSON matching the requested schema."
)


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


def build_formula_candidate_prompt(
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
            "task": (
                "Return 1-5 plausible formulas for the request. Reuse a local_formula_id only for "
                "an exact existing match; otherwise leave it empty. Give each candidate a concise "
                "summary and explain why it fits the request."
            ),
            "deduplication_policy": DEDUPLICATION_SKILL,
        },
        ensure_ascii=False,
    )


def parse_formula_candidates(raw: str) -> list[FormulaCandidate]:
    data = _json_object(raw)
    items = data.get("candidates")
    if not isinstance(items, list):
        raise SynthesisError("AI formula candidates response did not contain candidates")
    candidates = []
    seen = set()
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        candidate = FormulaCandidate(
            canonical_name=str(item.get("canonical_name", "")),
            latex=str(item.get("latex", "")),
            summary=str(item.get("summary", "")),
            topic=str(item.get("topic", "")),
            reason=str(item.get("reason", "")),
            confidence=item.get("confidence", 0),
            local_formula_id=str(item.get("local_formula_id", "")),
        )
        key = formula_key(candidate.canonical_name)
        if not candidate.canonical_name or not candidate.latex or not candidate.summary or key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    if not candidates:
        raise SynthesisError("AI formula candidates response contained no usable candidates")
    return candidates


def build_formula_synthesis_prompt(*, has_sources: bool) -> str:
    mode = "source_bounded_answer" if has_sources else "provider_native_answer"
    return (
        f"{FORMULA_SYNTHESIS_SKILL}\n{FORMULA_RELATIONSHIP_SKILL}\nCurrent mode: {mode}."
    )


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


def build_relationship_deep_dive_prompt(
    relationship: dict[str, Any],
    sources: Iterable[dict[str, Any]],
) -> str:
    relationship_payload = dict(relationship)
    task = (
        "Generate the session's initial long-form explanation of this AI-created relationship. "
        "Explain the mathematical connection independently and include only reliable source URLs."
    )
    if relationship_payload.get("created_by") == "manual":
        relationship_payload.pop("rationale", None)
        learner_note = str(relationship.get("rationale") or "").strip()
        if learner_note:
            relationship_payload["learner_note"] = learner_note
        task = (
            "Generate the session's initial long-form explanation of this AI-confirmed manual "
            "relationship. Incorporate learner_note, when present, as user-supplied context and "
            "compare it with reliable mathematical research. Include only reliable source URLs."
        )
    return json.dumps(
        {
            "skill_file": "mathernet/skills/relationship_deep_dive.md",
            "relationship": relationship_payload,
            "known_sources": list(sources),
            "task": task,
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


def build_relationship_validation_prompt(
    relationship: dict[str, Any],
    sources: Iterable[dict[str, Any]],
) -> str:
    return json.dumps(
        {
            "skill_file": "mathernet/skills/relationship_deep_dive.md",
            "relationship": relationship,
            "known_sources": list(sources),
            "task": (
                "Verify whether the stated relationship is mathematically meaningful. Assess the "
                "learner's explanation on its own, then use web research when available to look for "
                "independent support. Return only sources that actually support this relationship."
            ),
        },
        ensure_ascii=False,
    )


def parse_relationship_validation(raw: str) -> dict[str, Any]:
    data = _json_object(raw)
    return {
        "explanation_is_reasonable": bool(data.get("explanation_is_reasonable")),
        "web_supported": bool(data.get("web_supported")),
        "assessment": _text(data.get("assessment")),
        "sources": _source_items(data.get("sources")),
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
