from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from .errors import ValidationError


SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class FormulaStatus(StrEnum):
    NEW = "new"
    LEARNING = "learning"
    REVIEWED = "reviewed"
    NEEDS_REVIEW = "needs_review"


class EdgeRelation(StrEnum):
    PREREQUISITE = "prerequisite"
    DERIVATION_BASIS = "derivation_basis"
    SPECIAL_CASE = "special_case"
    GENERALIZATION = "generalization"
    EQUIVALENT_FORM = "equivalent_form"


class VerificationStatus(StrEnum):
    AI_SUGGESTED = "ai_suggested"
    USER_VERIFIED = "user_verified"
    USER_EDITED = "user_edited"
    REJECTED = "rejected"
    UNSUPPORTED = "unsupported"


class EdgeEvidence(StrEnum):
    SUPPORTED = "supported"
    UNVERIFIED = "unverified"


class RefusalReason(StrEnum):
    ASSESSMENT = "assessment_request"
    NON_FORMULA = "non_formula_request"
    NO_RELIABLE_SOURCE = "no_reliable_source"
    FABRICATION = "fabrication_request"


def _required_string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def _ensure_object_shape(
    data: Any,
    context: str,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValidationError(f"{context} must be an object")
    missing = set(required) - data.keys()
    if missing:
        raise ValidationError(
            f"{context} is missing required fields: {', '.join(sorted(missing))}"
        )
    unknown = data.keys() - set(required) - set(optional)
    if unknown:
        raise ValidationError(
            f"{context} contains unknown fields: {', '.join(sorted(unknown))}"
        )
    return data


def _required_timestamp(data: dict[str, Any], key: str, context: str) -> str:
    value = _required_string(data, key, context)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValidationError(f"{context}.{key} must be an ISO 8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValidationError(f"{context}.{key} must include a timezone")
    return value


def _string_list(data: dict[str, Any], key: str, context: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValidationError(f"{context}.{key} must be a list of strings")
    return [item.strip() for item in value if item.strip()]


def _validate_url(value: str, context: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError(f"{context} must contain a valid http(s) URL")


@dataclass(slots=True)
class SourceRecord:
    id: str
    title: str
    url: str
    publisher: str
    retrieved_at: str
    excerpt: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceRecord:
        context = "source"
        data = _ensure_object_shape(
            data,
            context,
            ("id", "title", "url", "publisher", "retrieved_at", "excerpt"),
        )
        source_id = _required_string(data, "id", context)
        title = _required_string(data, "title", context)
        url = _required_string(data, "url", context)
        publisher = _required_string(data, "publisher", context)
        retrieved_at = _required_timestamp(data, "retrieved_at", context)
        excerpt = _required_string(data, "excerpt", context)
        _validate_url(url, f"{context} {source_id}.url")
        return cls(source_id, title, url, publisher, retrieved_at, excerpt)


@dataclass(slots=True)
class AIModule:
    summary: str
    explanation: str
    examples: list[str] = field(default_factory=list)
    derivation_steps: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AIModule:
        context = "ai_module"
        data = _ensure_object_shape(
            data,
            context,
            ("summary", "explanation", "examples", "derivation_steps", "generated_at"),
        )
        return cls(
            summary=_required_string(data, "summary", context),
            explanation=_required_string(data, "explanation", context),
            examples=_string_list(data, "examples", context),
            derivation_steps=_string_list(data, "derivation_steps", context),
            generated_at=_required_timestamp(data, "generated_at", context),
        )


@dataclass(slots=True)
class UserModule:
    notes: str = ""
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserModule:
        context = "user_module"
        data = _ensure_object_shape(data, context, ("notes", "updated_at"))
        notes = data["notes"]
        if not isinstance(notes, str):
            raise ValidationError(f"{context}.notes must be a string")
        updated_at = _required_timestamp(data, "updated_at", context)
        return cls(notes, updated_at)


@dataclass(slots=True)
class FormulaNode:
    id: str
    name: str
    latex: str
    aliases: list[str]
    topic_tags: list[str]
    ai_module: AIModule
    user_module: UserModule
    status: FormulaStatus
    sources: list[str]
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FormulaNode:
        context = "formula"
        data = _ensure_object_shape(
            data,
            context,
            (
                "id",
                "name",
                "latex",
                "aliases",
                "topic_tags",
                "ai_module",
                "user_module",
                "status",
                "sources",
                "created_at",
                "updated_at",
            ),
        )
        formula_id = _required_string(data, "id", context)
        name = _required_string(data, "name", context)
        latex = _required_string(data, "latex", context)
        aliases = _string_list(data, "aliases", context)
        topic_tags = _string_list(data, "topic_tags", context)
        sources = _string_list(data, "sources", context)
        created_at = _required_timestamp(data, "created_at", context)
        updated_at = _required_timestamp(data, "updated_at", context)
        try:
            status = FormulaStatus(data.get("status"))
        except (TypeError, ValueError) as error:
            raise ValidationError(f"{context} {formula_id}.status is invalid") from error
        return cls(
            id=formula_id,
            name=name,
            latex=latex,
            aliases=aliases,
            topic_tags=topic_tags,
            ai_module=AIModule.from_dict(data["ai_module"]),
            user_module=UserModule.from_dict(data["user_module"]),
            status=status,
            sources=sources,
            created_at=created_at,
            updated_at=updated_at,
        )


@dataclass(slots=True)
class DependencyEdge:
    id: str
    source_id: str
    target_id: str
    relation: EdgeRelation
    rationale: str
    sources: list[str]
    verification_status: VerificationStatus
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    created_by: str = "ai"
    evidence_status: EdgeEvidence = EdgeEvidence.UNVERIFIED

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["relation"] = self.relation.value
        data["verification_status"] = self.verification_status.value
        data["evidence_status"] = self.evidence_status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DependencyEdge:
        context = "edge"
        data = _ensure_object_shape(
            data,
            context,
            (
                "id",
                "source_id",
                "target_id",
                "relation",
                "rationale",
                "sources",
                "verification_status",
                "created_at",
                "updated_at",
            ),
            optional=("created_by", "evidence_status"),
        )
        edge_id = _required_string(data, "id", context)
        source_id = _required_string(data, "source_id", context)
        target_id = _required_string(data, "target_id", context)
        rationale_value = data.get("rationale")
        if not isinstance(rationale_value, str):
            raise ValidationError(f"{context} {edge_id}.rationale must be a string")
        rationale = rationale_value.strip()
        sources = _string_list(data, "sources", context)
        created_at = _required_timestamp(data, "created_at", context)
        updated_at = _required_timestamp(data, "updated_at", context)
        try:
            relation = EdgeRelation(data.get("relation"))
        except (TypeError, ValueError) as error:
            raise ValidationError(f"{context} {edge_id}.relation is invalid") from error
        try:
            status = VerificationStatus(data.get("verification_status"))
        except (TypeError, ValueError) as error:
            raise ValidationError(
                f"{context} {edge_id}.verification_status is invalid"
            ) from error
        evidence_value = data.get("evidence_status")
        if evidence_value is None:
            evidence = EdgeEvidence.SUPPORTED if sources else EdgeEvidence.UNVERIFIED
        else:
            try:
                evidence = EdgeEvidence(evidence_value)
            except (TypeError, ValueError) as error:
                raise ValidationError(
                    f"{context} {edge_id}.evidence_status is invalid"
                ) from error
        return cls(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            rationale=rationale,
            sources=sources,
            verification_status=status,
            created_at=created_at,
            updated_at=updated_at,
            created_by=str(data.get("created_by") or "ai"),
            evidence_status=evidence,
        )


@dataclass(slots=True)
class GraphDocument:
    schema_version: int = SCHEMA_VERSION
    nodes: list[FormulaNode] = field(default_factory=list)
    edges: list[DependencyEdge] = field(default_factory=list)
    sources: list[SourceRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "sources": [source.to_dict() for source in self.sources],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphDocument:
        data = _ensure_object_shape(
            data,
            "graph",
            ("schema_version", "nodes", "edges", "sources"),
        )
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValidationError(
                f"unsupported schema_version {version!r}; expected {SCHEMA_VERSION}"
            )
        for key in ("nodes", "edges", "sources"):
            if not isinstance(data.get(key), list):
                raise ValidationError(f"{key} must be a list")
        return cls(
            schema_version=version,
            nodes=[FormulaNode.from_dict(item) for item in data["nodes"]],
            edges=[DependencyEdge.from_dict(item) for item in data["edges"]],
            sources=[SourceRecord.from_dict(item) for item in data["sources"]],
        )
