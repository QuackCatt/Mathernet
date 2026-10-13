from __future__ import annotations

import re
from typing import Iterable

from .errors import ValidationError
from .models import (
    DependencyEdge,
    EdgeRelation,
    FormulaNode,
    GraphDocument,
    SourceRecord,
    VerificationStatus,
)
from .normalization import formula_key, normalize_text


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
MAX_QUERY_LENGTH = 200
MAX_NAME_LENGTH = 200
MAX_LATEX_LENGTH = 4_000
MAX_SHORT_TEXT_LENGTH = 2_000
MAX_LONG_TEXT_LENGTH = 20_000
MAX_LIST_ITEMS = 50
MAX_TOPICS = 20
MAX_SOURCES_PER_OBJECT = 20

ACTIVE_EDGE_STATUSES = {
    VerificationStatus.AI_SUGGESTED,
    VerificationStatus.USER_VERIFIED,
    VerificationStatus.USER_EDITED,
}
ACCEPTED_EDGE_STATUSES = {
    VerificationStatus.USER_VERIFIED,
    VerificationStatus.USER_EDITED,
}
ACYCLIC_RELATIONS = {
    EdgeRelation.PREREQUISITE,
    EdgeRelation.DERIVATION_BASIS,
}
EDGE_TRANSITIONS = {
    VerificationStatus.AI_SUGGESTED: {
        VerificationStatus.AI_SUGGESTED,
        VerificationStatus.USER_VERIFIED,
        VerificationStatus.USER_EDITED,
        VerificationStatus.REJECTED,
        VerificationStatus.UNSUPPORTED,
    },
    VerificationStatus.USER_VERIFIED: {
        VerificationStatus.USER_VERIFIED,
        VerificationStatus.USER_EDITED,
        VerificationStatus.REJECTED,
    },
    VerificationStatus.USER_EDITED: {
        VerificationStatus.USER_VERIFIED,
        VerificationStatus.USER_EDITED,
        VerificationStatus.REJECTED,
    },
    VerificationStatus.REJECTED: {
        VerificationStatus.REJECTED,
        VerificationStatus.AI_SUGGESTED,
    },
    VerificationStatus.UNSUPPORTED: {
        VerificationStatus.UNSUPPORTED,
        VerificationStatus.AI_SUGGESTED,
    },
}


def validate_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValidationError(
            f"{field_name} must start with an alphanumeric character and contain only letters, numbers, '.', '_', ':', or '-'"
        )
    return value


def validate_bounded_text(
    value: str,
    field_name: str,
    *,
    max_length: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string")
    normalized = normalize_text(value)
    if not normalized and not allow_empty:
        raise ValidationError(f"{field_name} must not be empty")
    if len(normalized) > max_length:
        raise ValidationError(f"{field_name} must be at most {max_length} characters")
    return normalized


def validate_string_list(
    values: Iterable[str],
    field_name: str,
    *,
    max_items: int,
    item_max_length: int = MAX_SHORT_TEXT_LENGTH,
    allow_empty_items: bool = False,
) -> list[str]:
    items = list(values)
    if len(items) > max_items:
        raise ValidationError(f"{field_name} must contain at most {max_items} items")
    normalized: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        text = validate_bounded_text(
            item,
            f"{field_name}[{index}]",
            max_length=item_max_length,
            allow_empty=allow_empty_items,
        )
        key = formula_key(text)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return normalized


def validate_identifier_list(
    values: Iterable[str],
    field_name: str,
    *,
    max_items: int,
) -> list[str]:
    items = list(values)
    if len(items) > max_items:
        raise ValidationError(f"{field_name} must contain at most {max_items} items")
    normalized: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        value = validate_identifier(item, f"{field_name}[{index}]")
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def validate_formula_fields(
    *,
    formula_id: str,
    name: str,
    latex: str,
    aliases: Iterable[str],
    topic_tags: Iterable[str],
    sources: Iterable[str],
) -> None:
    validate_identifier(formula_id, "formula.id")
    validate_bounded_text(name, "formula.name", max_length=MAX_NAME_LENGTH)
    validate_bounded_text(latex, "formula.latex", max_length=MAX_LATEX_LENGTH)
    validate_string_list(aliases, "formula.aliases", max_items=MAX_LIST_ITEMS)
    validate_string_list(
        topic_tags,
        "formula.topic_tags",
        max_items=MAX_TOPICS,
        item_max_length=100,
    )
    validate_identifier_list(
        sources,
        "formula.sources",
        max_items=MAX_SOURCES_PER_OBJECT,
    )


def validate_edge_fields(
    *,
    edge_id: str,
    source_id: str,
    target_id: str,
    rationale: str,
    sources: Iterable[str],
) -> None:
    validate_identifier(edge_id, "edge.id")
    validate_identifier(source_id, "edge.source_id")
    validate_identifier(target_id, "edge.target_id")
    if source_id == target_id:
        raise ValidationError("an edge cannot connect a formula to itself")
    validate_bounded_text(
        rationale,
        "edge.rationale",
        max_length=MAX_LONG_TEXT_LENGTH,
    )
    source_ids = validate_identifier_list(
        sources,
        "edge.sources",
        max_items=MAX_SOURCES_PER_OBJECT,
    )
    if not source_ids:
        raise ValidationError("a dependency edge must reference at least one source")


def validate_edge_transition(
    current: VerificationStatus,
    requested: VerificationStatus,
) -> None:
    if requested not in EDGE_TRANSITIONS[current]:
        raise ValidationError(
            f"edge status cannot change from {current.value} to {requested.value}"
        )


def ensure_edge_addition_allowed(document: GraphDocument, candidate: DependencyEdge) -> None:
    validate_edge_fields(
        edge_id=candidate.id,
        source_id=candidate.source_id,
        target_id=candidate.target_id,
        rationale=candidate.rationale,
        sources=candidate.sources,
    )
    for edge in document.edges:
        if edge.source_id == candidate.source_id and edge.target_id == candidate.target_id:
            if edge.verification_status in ACTIVE_EDGE_STATUSES:
                raise ValidationError("this directed dependency edge already exists")
    if candidate.relation in ACYCLIC_RELATIONS:
        prospective = [
            edge
            for edge in document.edges
            if edge.verification_status in ACTIVE_EDGE_STATUSES
            and edge.relation in ACYCLIC_RELATIONS
        ] + [candidate]
        if _has_directed_cycle(prospective):
            raise ValidationError(
                "prerequisite and derivation-basis edges cannot form a dependency cycle"
            )


def validate_graph_rules(document: GraphDocument) -> None:
    node_ids: set[str] = set()
    source_ids: set[str] = set()
    edge_ids: set[str] = set()
    identities: dict[str, str] = {}

    for source in document.sources:
        SourceRecord.from_dict(source.to_dict())
        validate_identifier(source.id, "source.id")
        if source.id in source_ids:
            raise ValidationError(f"duplicate source ID {source.id}")
        source_ids.add(source.id)

    for node in document.nodes:
        FormulaNode.from_dict(node.to_dict())
        validate_formula_fields(
            formula_id=node.id,
            name=node.name,
            latex=node.latex,
            aliases=node.aliases,
            topic_tags=node.topic_tags,
            sources=node.sources,
        )
        if node.id in node_ids:
            raise ValidationError(f"duplicate formula ID {node.id}")
        node_ids.add(node.id)
        missing_sources = set(node.sources) - source_ids
        if missing_sources:
            raise ValidationError(
                f"formula {node.id} references missing sources: {sorted(missing_sources)}"
            )
        if node.ai_module.derivation_steps and not node.sources:
            raise ValidationError(
                f"formula {node.id} has derivation steps but no source coverage"
            )
        for identity in (node.name, *node.aliases):
            key = formula_key(identity)
            owner = identities.get(key)
            if owner is not None and owner != node.id:
                raise ValidationError(
                    f"formula identity {normalize_text(identity)!r} is shared by {owner} and {node.id}"
                )
            identities[key] = node.id

    for edge in document.edges:
        DependencyEdge.from_dict(edge.to_dict())
        validate_edge_fields(
            edge_id=edge.id,
            source_id=edge.source_id,
            target_id=edge.target_id,
            rationale=edge.rationale,
            sources=edge.sources,
        )
        if edge.id in edge_ids:
            raise ValidationError(f"duplicate edge ID {edge.id}")
        edge_ids.add(edge.id)
        if edge.source_id not in node_ids or edge.target_id not in node_ids:
            raise ValidationError(f"edge {edge.id} references a missing formula")
        missing_sources = set(edge.sources) - source_ids
        if missing_sources:
            raise ValidationError(
                f"edge {edge.id} references missing sources: {sorted(missing_sources)}"
            )

    active_pairs: set[tuple[str, str]] = set()
    for edge in document.edges:
        if edge.verification_status not in ACTIVE_EDGE_STATUSES:
            continue
        pair = (edge.source_id, edge.target_id)
        if pair in active_pairs:
            raise ValidationError(
                f"multiple active edges connect {edge.source_id} -> {edge.target_id}"
            )
        active_pairs.add(pair)
    active_edges = [
        edge
        for edge in document.edges
        if edge.verification_status in ACTIVE_EDGE_STATUSES
        and edge.relation in ACYCLIC_RELATIONS
    ]
    if _has_directed_cycle(active_edges):
        raise ValidationError(
            "prerequisite and derivation-basis edges cannot form a dependency cycle"
        )


def _has_directed_cycle(edges: Iterable[DependencyEdge]) -> bool:
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source_id, []).append(edge.target_id)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        for target_id in adjacency.get(node_id, []):
            if visit(target_id):
                return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    return any(visit(node_id) for node_id in list(adjacency))
