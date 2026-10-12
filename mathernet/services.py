from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from .agent import FormulaAgent, LearnResult
from .config import Settings
from .errors import ConflictError, NotFoundError, ValidationError
from .llm import OpenAIResponsesSynthesizer, RuleBasedSynthesizer
from .models import (
    DependencyEdge,
    EdgeRelation,
    FormulaNode,
    FormulaStatus,
    VerificationStatus,
)
from .normalization import formula_key, normalize_text
from .repository import GraphRepository
from .retrieval import provider_from_settings
from .rules import (
    ACCEPTED_EDGE_STATUSES,
    ACTIVE_EDGE_STATUSES,
    MAX_QUERY_LENGTH,
    validate_bounded_text,
)


class LearningAgent(Protocol):
    def learn(self, query: str) -> LearnResult: ...


class MathernetService:
    def __init__(self, repository: GraphRepository, agent: LearningAgent | None = None):
        self.repository = repository
        self.agent = agent

    @property
    def revision(self) -> str:
        payload = json.dumps(
            self.repository.document.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def health(self) -> dict[str, Any]:
        document = self.repository.document
        return {
            "status": "ok",
            "schema_version": document.schema_version,
            "formula_count": len(document.nodes),
            "edge_count": len(document.edges),
            "source_count": len(document.sources),
            "pending_edge_count": sum(
                edge.verification_status == VerificationStatus.AI_SUGGESTED
                for edge in document.edges
            ),
            "revision": self.revision,
        }

    def list_formulas(
        self,
        *,
        query: str = "",
        status: str | None = None,
        topic: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        query = validate_bounded_text(
            query,
            "query",
            max_length=MAX_QUERY_LENGTH,
            allow_empty=True,
        )
        if limit < 1 or limit > 200:
            raise ValidationError("limit must be between 1 and 200")
        if offset < 0:
            raise ValidationError("offset must be zero or greater")
        parsed_status = self._parse_status(status) if status else None
        normalized_topic = normalize_text(topic) if topic else ""

        items = []
        query_key = formula_key(query)
        for node in self.repository.list_formulas():
            identities = [node.id, node.name, *node.aliases]
            if query_key and not any(query_key in formula_key(item) for item in identities):
                continue
            if parsed_status is not None and node.status != parsed_status:
                continue
            if normalized_topic and normalized_topic.casefold() not in {
                item.casefold() for item in node.topic_tags
            }:
                continue
            items.append(self._formula_summary(node))

        return {
            "items": items[offset : offset + limit],
            "total": len(items),
            "limit": limit,
            "offset": offset,
            "revision": self.revision,
        }

    def get_formula_card(self, formula_ref: str) -> dict[str, Any]:
        node = self.resolve_formula(formula_ref)
        return self._formula_card(node)

    def get_edge_payload(self, edge_id: str) -> dict[str, Any]:
        return self._edge_payload(self.repository.get_edge(edge_id))

    def get_graph(self, formula_ref: str, *, depth: int = 1) -> dict[str, Any]:
        if depth < 1 or depth > 3:
            raise ValidationError("depth must be between 1 and 3")
        start = self.resolve_formula(formula_ref)
        node_ids = {start.id}
        frontier = {start.id}
        for _ in range(depth):
            next_frontier: set[str] = set()
            for edge in self.repository.document.edges:
                if edge.verification_status not in ACTIVE_EDGE_STATUSES:
                    continue
                if edge.source_id in frontier and edge.target_id not in node_ids:
                    next_frontier.add(edge.target_id)
                if edge.target_id in frontier and edge.source_id not in node_ids:
                    next_frontier.add(edge.source_id)
            if not next_frontier:
                break
            node_ids.update(next_frontier)
            frontier = next_frontier

        nodes = [
            self._formula_summary(self.repository.get_formula(node_id))
            for node_id in sorted(node_ids)
        ]
        edges = [
            self._edge_payload(edge)
            for edge in self.repository.document.edges
            if edge.verification_status in ACTIVE_EDGE_STATUSES
            and edge.source_id in node_ids
            and edge.target_id in node_ids
        ]
        return {
            "root_id": start.id,
            "depth": depth,
            "nodes": nodes,
            "edges": edges,
            "revision": self.revision,
        }

    def update_user_module(
        self,
        formula_ref: str,
        notes: str,
        *,
        expected_updated_at: str | None = None,
    ) -> dict[str, Any]:
        node = self.resolve_formula(formula_ref)
        self._ensure_node_version(node, expected_updated_at)
        updated = self.repository.update_user_module(node.id, notes)
        self.repository.save()
        return self._formula_card(updated)

    def set_formula_status(
        self,
        formula_ref: str,
        status: str,
        *,
        expected_updated_at: str | None = None,
    ) -> dict[str, Any]:
        node = self.resolve_formula(formula_ref)
        self._ensure_node_version(node, expected_updated_at)
        updated = self.repository.set_formula_status(node.id, self._parse_status(status))
        self.repository.save()
        return self._formula_card(updated)

    def add_edge(
        self,
        *,
        source_ref: str,
        target_ref: str,
        relation: str,
        rationale: str,
        source_ids: list[str],
        edge_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(source_ids, list):
            raise ValidationError("source_ids must be an array")
        source = self.resolve_formula(source_ref)
        target = self.resolve_formula(target_ref)
        new_edge_id = self.repository.unique_edge_id(
            edge_id or self._edge_id_base(source.id, target.id)
        )
        edge = self.repository.add_edge(
            edge_id=new_edge_id,
            source_id=source.id,
            target_id=target.id,
            relation=self._parse_relation(relation),
            rationale=rationale,
            sources=source_ids,
        )
        self.repository.save()
        return self._edge_payload(edge)

    def update_edge(
        self,
        edge_id: str,
        *,
        relation: str,
        rationale: str,
        source_ids: list[str],
        expected_updated_at: str | None = None,
    ) -> dict[str, Any]:
        edge = self.repository.get_edge(edge_id)
        self._ensure_edge_version(edge, expected_updated_at)
        updated = self.repository.edit_edge(
            edge.id,
            relation=self._parse_relation(relation),
            rationale=rationale,
            sources=source_ids,
        )
        self.repository.save()
        return self._edge_payload(updated)

    def confirm_edge(
        self,
        edge_id: str,
        *,
        expected_updated_at: str | None = None,
    ) -> dict[str, Any]:
        edge = self.repository.get_edge(edge_id)
        self._ensure_edge_version(edge, expected_updated_at)
        updated = self.repository.verify_edge(edge.id)
        self.repository.save()
        return self._edge_payload(updated)

    def reject_edge(
        self,
        edge_id: str,
        *,
        expected_updated_at: str | None = None,
    ) -> dict[str, Any]:
        edge = self.repository.get_edge(edge_id)
        self._ensure_edge_version(edge, expected_updated_at)
        updated = self.repository.reject_edge(edge.id)
        self.repository.save()
        return self._edge_payload(updated)

    def learn(self, query: str) -> dict[str, Any]:
        query = validate_bounded_text(query, "query", max_length=MAX_QUERY_LENGTH)
        if self.agent is None:
            raise ValidationError("online learning is not configured for this service")
        result = self.agent.learn(query)
        return {
            "created": result.created,
            "formula": self._formula_card(result.node),
            "suggested_edges": [self._edge_payload(edge) for edge in result.edges],
            "unresolved_dependencies": result.unresolved_dependencies,
            "warnings": result.warnings,
            "revision": self.revision,
        }

    def export_graph(self) -> dict[str, Any]:
        return self.repository.document.to_dict()

    def resolve_formula(self, formula_ref: str) -> FormulaNode:
        formula_ref = validate_bounded_text(
            formula_ref,
            "formula",
            max_length=MAX_QUERY_LENGTH,
        )
        for node in self.repository.document.nodes:
            if node.id == formula_ref:
                return node
        node = self.repository.find_formula(formula_ref)
        if node is None:
            raise NotFoundError(f"formula {formula_ref} was not found")
        return node

    def _formula_summary(self, node: FormulaNode) -> dict[str, Any]:
        return {
            "id": node.id,
            "name": node.name,
            "latex": node.latex,
            "display": self._display_latex(node.latex),
            "aliases": node.aliases,
            "topic_tags": node.topic_tags,
            "status": node.status.value,
            "source_count": len(node.sources),
            "updated_at": node.updated_at,
        }

    def _formula_card(self, node: FormulaNode) -> dict[str, Any]:
        incoming, outgoing = self.repository.neighbours(node.id)
        return {
            "formula": node.to_dict(),
            "display": self._display_latex(node.latex),
            "sources": [
                self.repository.get_source(source_id).to_dict()
                for source_id in node.sources
            ],
            "incoming_edges": [self._edge_payload(edge) for edge in incoming],
            "outgoing_edges": [self._edge_payload(edge) for edge in outgoing],
            "revision": self.revision,
        }

    def _edge_payload(self, edge: DependencyEdge) -> dict[str, Any]:
        source = self.repository.get_formula(edge.source_id)
        target = self.repository.get_formula(edge.target_id)
        return {
            "id": edge.id,
            "source_id": edge.source_id,
            "source_name": source.name,
            "target_id": edge.target_id,
            "target_name": target.name,
            "relation": edge.relation.value,
            "rationale": edge.rationale,
            "sources": [
                self.repository.get_source(source_id).to_dict()
                for source_id in edge.sources
            ],
            "verification_status": edge.verification_status.value,
            "requires_user_confirmation": (
                edge.verification_status == VerificationStatus.AI_SUGGESTED
            ),
            "accepted": edge.verification_status in ACCEPTED_EDGE_STATUSES,
            "created_at": edge.created_at,
            "updated_at": edge.updated_at,
        }

    @staticmethod
    def _display_latex(latex: str) -> str:
        from .normalization import latex_to_ascii

        return latex_to_ascii(latex)

    @staticmethod
    def _parse_status(value: str) -> FormulaStatus:
        try:
            return FormulaStatus(value)
        except (TypeError, ValueError) as error:
            raise ValidationError(f"unsupported formula status {value!r}") from error

    @staticmethod
    def _parse_relation(value: str) -> EdgeRelation:
        try:
            return EdgeRelation(value)
        except (TypeError, ValueError) as error:
            raise ValidationError(f"unsupported edge relation {value!r}") from error

    @staticmethod
    def _ensure_node_version(node: FormulaNode, expected_updated_at: str | None) -> None:
        if expected_updated_at is not None and expected_updated_at != node.updated_at:
            raise ConflictError("the formula was updated by another action; reload it and retry")

    @staticmethod
    def _ensure_edge_version(edge: DependencyEdge, expected_updated_at: str | None) -> None:
        if expected_updated_at is not None and expected_updated_at != edge.updated_at:
            raise ConflictError("the edge was updated by another action; reload it and retry")

    @staticmethod
    def _edge_id_base(source_id: str, target_id: str) -> str:
        digest = hashlib.sha256(f"{source_id}->{target_id}".encode("utf-8")).hexdigest()[:12]
        return f"edge_{digest}"


def build_service(settings: Settings) -> MathernetService:
    repository = GraphRepository(settings.data_path)
    synthesizer = (
        OpenAIResponsesSynthesizer(
            settings.openai_api_key,
            settings.openai_model,
            settings.request_timeout_seconds,
        )
        if settings.openai_api_key
        else RuleBasedSynthesizer()
    )
    agent = FormulaAgent(
        repository,
        provider_from_settings(settings),
        synthesizer,
        settings.approved_publishers,
    )
    return MathernetService(repository, agent)
