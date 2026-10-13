from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Protocol

from .agent import FormulaAgent, LearnResult
from .config import Settings
from .errors import ConflictError, NotFoundError, ValidationError
from .llm import OpenAIResponsesSynthesizer, RuleBasedSynthesizer
from .gateway import GatewayConfig, GatewayStore, ProviderGateway, SearchGateway
from .models import (
    DependencyEdge,
    EdgeRelation,
    FormulaNode,
    FormulaStatus,
    VerificationStatus,
)
from .normalization import formula_key, normalize_text
from .providers import provider_catalog
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
    def __init__(
        self,
        repository: GraphRepository,
        agent: LearningAgent | None = None,
        gateway_store: GatewayStore | None = None,
    ):
        self.repository = repository
        self.agent = agent
        self.gateway_store = gateway_store or GatewayStore()

    def gateway_config(self) -> dict[str, Any]:
        config = self.gateway_store.load()
        providers = provider_catalog()
        return {
            **config.public_dict(),
            "providers": [provider["id"] for provider in providers],
            "provider_presets": providers,
            "search_engines": ["google", "bing", "yahoo", "baidu"],
            "first_run": not config.ai_configured,
        }

    def save_gateway_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.gateway_store.load()
        payload = dict(payload)
        aliases = {
            "transport": "mcp_transport",
            "command": "mcp_command",
            "http_url": "mcp_http_url",
            "tool_name": "mcp_tool_name",
            "headers_json": "mcp_headers",
        }
        for source, target in aliases.items():
            if source in payload and target not in payload:
                payload[target] = payload[source]
        fields = {
            "provider", "api_key", "model", "api_format", "base_url", "endpoint_path",
            "auth_style", "search_engine", "search_api_key",
            "search_engine_id", "mcp_transport", "mcp_command", "mcp_http_url",
            "mcp_tool_name", "mcp_headers",
        }
        values = {}
        for field in fields:
            value = payload.get(field, getattr(current, field))
            if field in {"api_key", "search_api_key", "mcp_headers"} and not str(value).strip():
                value = getattr(current, field)
            values[field] = value
        provider = str(values.get("provider", "")).strip().lower()
        protocol_fields = {"api_format", "base_url", "endpoint_path", "auth_style"}
        if provider and provider != current.provider and not protocol_fields.intersection(payload):
            for field in protocol_fields:
                values[field] = ""
        search_engine = str(values.get("search_engine", "")).strip().lower()
        if search_engine and search_engine not in {"google", "bing", "yahoo", "baidu"}:
            raise ValidationError("unsupported search engine")
        config = GatewayConfig(
            provider=provider,
            api_key=str(values.get("api_key", current.api_key)),
            model=str(values.get("model", current.model)).strip(),
            api_format=str(values.get("api_format", current.api_format)),
            base_url=str(values.get("base_url", current.base_url)),
            endpoint_path=str(values.get("endpoint_path", current.endpoint_path)),
            auth_style=str(values.get("auth_style", current.auth_style)),
            search_engine=search_engine,
            search_api_key=str(values.get("search_api_key", current.search_api_key)),
            search_engine_id=str(values.get("search_engine_id", current.search_engine_id)),
            mcp_transport=str(values.get("mcp_transport", current.mcp_transport)).strip().lower(),
            mcp_command=str(values.get("mcp_command", current.mcp_command)).strip(),
            mcp_http_url=str(values.get("mcp_http_url", current.mcp_http_url)).strip(),
            mcp_tool_name=str(values.get("mcp_tool_name", current.mcp_tool_name)).strip() or "search",
            mcp_headers=str(values.get("mcp_headers", current.mcp_headers)).strip(),
            configured_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
        if config.provider and not config.model:
            raise ValidationError("model is required when an AI provider is selected")
        if config.provider:
            config.resolved_provider()
        self.gateway_store.save(config)
        self._rebuild_agent(config)
        return self.gateway_config()

    def test_gateway_ai(self) -> dict[str, Any]:
        return ProviderGateway(self.gateway_store.load()).test_connection()

    def test_gateway_search(self) -> dict[str, Any]:
        return SearchGateway(self.gateway_store.load()).test_connection()

    def _rebuild_agent(self, config: GatewayConfig) -> None:
        publishers = getattr(self.agent, "approved_publishers", ())
        synthesizer = ProviderGateway(config) if config.ai_configured else RuleBasedSynthesizer()
        self.agent = FormulaAgent(
            self.repository,
            SearchGateway(config).provider(),
            synthesizer,
            publishers,
        )

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
    gateway_store = GatewayStore(settings.search_cache_path.parent / "gateway.json")
    config = gateway_store.load()
    if not config.completed:
        config = GatewayConfig(
            provider="openai" if settings.openai_api_key else "",
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            search_engine="",
            mcp_transport=settings.mcp_transport,
            mcp_command=" ".join(settings.mcp_command),
            mcp_http_url=settings.mcp_http_url,
            mcp_tool_name=settings.mcp_tool_name,
            mcp_headers=settings.mcp_headers,
        )
    synthesizer = ProviderGateway(config, settings.request_timeout_seconds) if config.ai_configured else RuleBasedSynthesizer()
    agent = FormulaAgent(
        repository,
        SearchGateway(config, settings.request_timeout_seconds).provider(),
        synthesizer,
        settings.approved_publishers,
    )
    return MathernetService(repository, agent, gateway_store)
