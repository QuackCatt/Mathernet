from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .errors import NotFoundError, ValidationError
from .models import (
    AIModule,
    DependencyEdge,
    EdgeRelation,
    FormulaNode,
    FormulaStatus,
    SourceRecord,
    UserModule,
    VerificationStatus,
    utc_now,
)
from .normalization import formula_key, normalize_text
from .rules import (
    MAX_LONG_TEXT_LENGTH,
    ensure_edge_addition_allowed,
    validate_bounded_text,
    validate_edge_fields,
    validate_edge_transition,
    validate_formula_fields,
    validate_graph_rules,
)
from .storage import JsonGraphStore


class GraphRepository:
    def __init__(self, path: Path | str):
        self.store = JsonGraphStore(path)
        self.document = self.store.load()

    def save(self) -> None:
        self._validate_references()
        self.store.save(self.document)

    def reload(self) -> None:
        self.document = self.store.load()
        self._validate_references()

    def find_formula(self, query: str) -> FormulaNode | None:
        key = formula_key(query)
        for node in self.document.nodes:
            candidates = [node.id, node.name, *node.aliases]
            if any(formula_key(candidate) == key for candidate in candidates):
                return node
        return None

    def get_formula(self, formula_id: str) -> FormulaNode:
        for node in self.document.nodes:
            if node.id == formula_id:
                return node
        raise NotFoundError(f"formula {formula_id} was not found")

    def list_formulas(self) -> list[FormulaNode]:
        return sorted(self.document.nodes, key=lambda node: node.name.casefold())

    def get_source(self, source_id: str) -> SourceRecord:
        for source in self.document.sources:
            if source.id == source_id:
                return source
        raise NotFoundError(f"source {source_id} was not found")

    def add_or_update_source(self, source: SourceRecord) -> SourceRecord:
        for index, existing in enumerate(self.document.sources):
            if existing.id == source.id and existing.url != source.url:
                raise ValidationError(f"source ID {source.id} is already used by another URL")
            if existing.url == source.url:
                merged = replace(
                    existing,
                    title=source.title or existing.title,
                    publisher=source.publisher or existing.publisher,
                    excerpt=source.excerpt or existing.excerpt,
                )
                self.document.sources[index] = merged
                return merged
        self.document.sources.append(source)
        return source

    def add_formula(
        self,
        *,
        formula_id: str,
        name: str,
        latex: str,
        aliases: list[str],
        topic_tags: list[str],
        ai_module: AIModule,
        sources: list[str],
    ) -> FormulaNode:
        validate_formula_fields(
            formula_id=formula_id,
            name=name,
            latex=latex,
            aliases=aliases,
            topic_tags=topic_tags,
            sources=sources,
        )
        if self.find_formula(name) or any(self.find_formula(alias) for alias in aliases):
            raise ValidationError("a formula with the same name or alias already exists")
        if any(node.id == formula_id for node in self.document.nodes):
            raise ValidationError(f"formula ID {formula_id} already exists")
        now = utc_now()
        node = FormulaNode(
            id=formula_id,
            name=normalize_text(name),
            latex=normalize_text(latex),
            aliases=[normalize_text(alias) for alias in aliases],
            topic_tags=[normalize_text(tag) for tag in topic_tags],
            ai_module=ai_module,
            user_module=UserModule(updated_at=now),
            status=FormulaStatus.NEW,
            sources=list(dict.fromkeys(sources)),
            created_at=now,
            updated_at=now,
        )
        self.document.nodes.append(node)
        self._validate_references()
        return node

    def update_user_module(self, formula_id: str, notes: str) -> FormulaNode:
        node = self.get_formula(formula_id)
        normalized_notes = validate_bounded_text(
            notes,
            "user_module.notes",
            max_length=MAX_LONG_TEXT_LENGTH,
            allow_empty=True,
        )
        now = utc_now()
        node.user_module = UserModule(notes=normalized_notes, updated_at=now)
        node.updated_at = now
        return node

    def set_formula_status(self, formula_id: str, status: FormulaStatus) -> FormulaNode:
        node = self.get_formula(formula_id)
        node.status = status
        now = utc_now()
        node.updated_at = now
        return node

    def add_edge(
        self,
        *,
        edge_id: str,
        source_id: str,
        target_id: str,
        relation: EdgeRelation,
        rationale: str,
        sources: list[str],
    ) -> DependencyEdge:
        try:
            relation = EdgeRelation(relation)
        except (TypeError, ValueError) as error:
            raise ValidationError(f"unsupported edge relation {relation!r}") from error
        validate_edge_fields(
            edge_id=edge_id,
            source_id=source_id,
            target_id=target_id,
            rationale=rationale,
            sources=sources,
        )
        if any(edge.id == edge_id for edge in self.document.edges):
            raise ValidationError(f"edge ID {edge_id} already exists")
        self.get_formula(source_id)
        self.get_formula(target_id)
        edge = DependencyEdge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            rationale=normalize_text(rationale),
            sources=list(dict.fromkeys(sources)),
            verification_status=VerificationStatus.AI_SUGGESTED,
        )
        ensure_edge_addition_allowed(self.document, edge)
        self.document.edges.append(edge)
        self._validate_references()
        return edge

    def get_edge(self, edge_id: str) -> DependencyEdge:
        for edge in self.document.edges:
            if edge.id == edge_id:
                return edge
        raise NotFoundError(f"edge {edge_id} was not found")

    def unique_edge_id(self, preferred: str) -> str:
        existing = {edge.id for edge in self.document.edges}
        if preferred not in existing:
            return preferred
        counter = 2
        while f"{preferred}_{counter}" in existing:
            counter += 1
        return f"{preferred}_{counter}"

    def verify_edge(self, edge_id: str, edited: bool = False) -> DependencyEdge:
        edge = self.get_edge(edge_id)
        requested_status = (
            VerificationStatus.USER_EDITED if edited else VerificationStatus.USER_VERIFIED
        )
        validate_edge_transition(edge.verification_status, requested_status)
        if edge.verification_status != requested_status:
            edge.verification_status = requested_status
            edge.updated_at = utc_now()
        return edge

    def reject_edge(self, edge_id: str) -> DependencyEdge:
        edge = self.get_edge(edge_id)
        validate_edge_transition(edge.verification_status, VerificationStatus.REJECTED)
        if edge.verification_status != VerificationStatus.REJECTED:
            edge.verification_status = VerificationStatus.REJECTED
            edge.updated_at = utc_now()
        return edge

    def edit_edge(
        self,
        edge_id: str,
        *,
        relation: EdgeRelation,
        rationale: str,
        sources: list[str],
    ) -> DependencyEdge:
        try:
            relation = EdgeRelation(relation)
        except (TypeError, ValueError) as error:
            raise ValidationError(f"unsupported edge relation {relation!r}") from error
        edge = self.get_edge(edge_id)
        validate_edge_fields(
            edge_id=edge.id,
            source_id=edge.source_id,
            target_id=edge.target_id,
            rationale=rationale,
            sources=sources,
        )
        validate_edge_transition(edge.verification_status, VerificationStatus.USER_EDITED)
        now = utc_now()
        edge.relation = relation
        edge.rationale = normalize_text(rationale)
        edge.sources = list(dict.fromkeys(sources))
        edge.verification_status = VerificationStatus.USER_EDITED
        edge.updated_at = now
        self._validate_references()
        return edge

    def neighbours(self, formula_id: str) -> tuple[list[DependencyEdge], list[DependencyEdge]]:
        self.get_formula(formula_id)
        incoming = [edge for edge in self.document.edges if edge.target_id == formula_id]
        outgoing = [edge for edge in self.document.edges if edge.source_id == formula_id]
        return incoming, outgoing

    def _validate_references(self) -> None:
        validate_graph_rules(self.document)
