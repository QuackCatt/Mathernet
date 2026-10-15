from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Protocol

from .agent import FormulaAgent, LearnResult
from .config import Settings
from .deep_dive_sessions import DeepDiveSessionStore, MAX_SESSION_MESSAGE_LENGTH, MAX_SESSION_REPLY_LENGTH
from .errors import ConflictError, NotFoundError, SynthesisError, ValidationError
from .formula_introductions import FormulaIntroductionStore
from .llm import RuleBasedSynthesizer
from .gateway import GatewayConfig, GatewayStore, ProviderGateway, SearchGateway
from .map_sessions import MapSessionStore
from .models import (
    DependencyEdge,
    EdgeEvidence,
    EdgeRelation,
    FormulaNode,
    FormulaStatus,
    SourceRecord,
    VerificationStatus,
    utc_now,
)
from .normalization import formula_key, normalize_text
from .providers import fetch_provider_models, provider_catalog
from .repository import GraphRepository
from .retrieval import provider_from_settings
from .rules import (
    ACCEPTED_EDGE_STATUSES,
    ACTIVE_EDGE_STATUSES,
    MAX_QUERY_LENGTH,
    validate_bounded_text,
)


class LearningAgent(Protocol):
    def learn(self, query: str, map_context: dict[str, Any] | None = None) -> LearnResult: ...


class DeepDiveGateway(Protocol):
    def validate_relationship(
        self,
        relationship: dict[str, Any],
        sources: list[dict[str, Any]],
    ) -> dict[str, Any]: ...

    def introduce(
        self,
        formula: dict[str, Any],
        sources: list[dict[str, Any]],
    ) -> str: ...

    def deep_dive(
        self,
        formula: dict[str, Any],
        sources: list[dict[str, Any]],
    ) -> dict[str, Any]: ...

    def deep_dive_relationship(
        self,
        relationship: dict[str, Any],
        sources: list[dict[str, Any]],
    ) -> dict[str, Any]: ...

    def chat(
        self,
        formula: dict[str, Any],
        deep_dive: dict[str, Any],
        messages: list[dict[str, str]],
    ) -> str: ...


class MathernetService:
    def __init__(
        self,
        repository: GraphRepository,
        agent: LearningAgent | None = None,
        gateway_store: GatewayStore | None = None,
        ai_gateway: DeepDiveGateway | None = None,
        deep_dive_sessions: DeepDiveSessionStore | None = None,
        formula_introductions: FormulaIntroductionStore | None = None,
        map_sessions: MapSessionStore | None = None,
    ):
        self.repository = repository
        self.agent = agent
        self.gateway_store = gateway_store or GatewayStore()
        self.ai_gateway = ai_gateway
        self.deep_dive_sessions = deep_dive_sessions or DeepDiveSessionStore()
        self.formula_introductions = formula_introductions or FormulaIntroductionStore()
        self.map_sessions = map_sessions or MapSessionStore()

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
        provider_changed = provider != current.provider
        protocol_fields = {"api_format", "base_url", "endpoint_path", "auth_style"}
        if provider_changed:
            for field in protocol_fields:
                if field not in payload:
                    values[field] = ""
            if "model" not in payload:
                values["model"] = ""
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
            ai_connection_status="unknown",
            ai_connection_message="",
            ai_connection_checked_at="",
        )
        if config.provider:
            config.resolved_provider()
        self.gateway_store.save(config)
        self._rebuild_agent(config)
        return self.gateway_config()

    def list_provider_models(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider", "")).strip().lower()
        current = self.gateway_store.load()
        api_key = str(payload.get("api_key", "")).strip()
        if not api_key and current.provider == provider:
            api_key = current.api_key
        models = fetch_provider_models(provider, api_key)
        provider_catalog_item = next(
            (item for item in provider_catalog() if item["id"] == provider),
            None,
        )
        return {
            "provider": provider,
            "models": models,
            "default_model": provider_catalog_item["default_model"] if provider_catalog_item else "",
        }

    def test_gateway_ai(self) -> dict[str, Any]:
        config = self.gateway_store.load()
        checked_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        try:
            result = ProviderGateway(config).test_connection()
        except SynthesisError as error:
            config.ai_connection_status = "check_settings"
            config.ai_connection_message = str(error)
            config.ai_connection_checked_at = checked_at
            self.gateway_store.save(config)
            self._rebuild_agent(config)
            raise
        config.ai_connection_status = "connected"
        config.ai_connection_message = str(result.get("message", "connected"))
        config.ai_connection_checked_at = checked_at
        self.gateway_store.save(config)
        self._rebuild_agent(config)
        return {
            **result,
            "ai_connection_status": config.ai_connection_status,
            "ai_connection_message": config.ai_connection_message,
            "ai_connection_checked_at": config.ai_connection_checked_at,
        }

    def test_gateway_search(self) -> dict[str, Any]:
        return SearchGateway(self.gateway_store.load()).test_connection()

    def _rebuild_agent(self, config: GatewayConfig) -> None:
        publishers = getattr(self.agent, "approved_publishers", ())
        synthesizer = ProviderGateway(config) if config.ai_configured else RuleBasedSynthesizer()
        self.ai_gateway = synthesizer if isinstance(synthesizer, ProviderGateway) else None
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
        status_counts = {"all": 0, "learning": 0, "reviewed": 0}
        query_key = formula_key(query)
        for node in self.repository.list_formulas():
            identities = [node.id, node.name, *node.aliases]
            if query_key and not any(query_key in formula_key(item) for item in identities):
                continue
            if normalized_topic and normalized_topic.casefold() not in {
                item.casefold() for item in node.topic_tags
            }:
                continue
            status_counts["all"] += 1
            status_value = node.status.value
            if status_value in status_counts:
                status_counts[status_value] += 1
            if parsed_status is not None and node.status != parsed_status:
                continue
            items.append(self._formula_summary(node))

        return {
            "items": items[offset : offset + limit],
            "total": len(items),
            "status_counts": status_counts,
            "limit": limit,
            "offset": offset,
            "revision": self.revision,
        }

    def get_formula_card(self, formula_ref: str) -> dict[str, Any]:
        node = self.resolve_formula(formula_ref)
        return self._formula_card(node)

    def get_formula_introduction(self, formula_ref: str) -> dict[str, Any]:
        node = self.resolve_formula(formula_ref)
        cached = self.formula_introductions.get(node.id)
        if cached is not None:
            return {**cached, "cached": True}

        card = self._formula_card(node)
        introduction = self._require_ai_gateway().introduce(
            self._formula_context(node),
            card["sources"],
        )
        saved = self.formula_introductions.save(node.id, introduction)
        return {**saved, "cached": False}

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
        manual: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(source_ids, list):
            raise ValidationError("source_ids must be an array")
        source = self.resolve_formula(source_ref)
        target = self.resolve_formula(target_ref)
        parsed_relation = self._parse_relation(relation)
        evidence_status = (
            EdgeEvidence.SUPPORTED if source_ids else EdgeEvidence.UNVERIFIED
        )
        if manual:
            source_ids, evidence_status = self._validate_manual_relationship(
                source=source,
                target=target,
                relation=parsed_relation,
                rationale=rationale,
                source_ids=source_ids,
            )
        new_edge_id = self.repository.unique_edge_id(
            edge_id or self._edge_id_base(source.id, target.id)
        )
        edge = self.repository.add_edge(
            edge_id=new_edge_id,
            source_id=source.id,
            target_id=target.id,
            relation=parsed_relation,
            rationale=rationale,
            sources=source_ids,
            manual=manual,
            evidence_status=evidence_status,
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

    def delete_edge(
        self,
        edge_id: str,
        *,
        expected_updated_at: str | None = None,
    ) -> dict[str, Any]:
        edge = self.repository.get_edge(edge_id)
        self._ensure_edge_version(edge, expected_updated_at)
        self.repository.delete_edge(edge.id)
        self.repository.save()
        return {
            "deleted": True,
            "edge_id": edge.id,
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "revision": self.revision,
        }

    def learn(
        self,
        query: str,
        *,
        map_session_id: str | None = None,
    ) -> dict[str, Any]:
        query = validate_bounded_text(query, "query", max_length=MAX_QUERY_LENGTH)
        if self.agent is None:
            raise ValidationError("online learning is not configured for this service")
        map_context = self._learning_map_context(map_session_id)
        if map_session_id:
            result = self.agent.learn(query, map_context)
        else:
            result = self.agent.learn(query)
        return {
            "created": result.created,
            "formula": self._formula_card(result.node),
            "suggested_edges": [self._edge_payload(edge) for edge in result.edges],
            "unresolved_dependencies": result.unresolved_dependencies,
            "warnings": result.warnings,
            "revision": self.revision,
        }

    def _learning_map_context(self, map_session_id: str | None) -> dict[str, Any]:
        if not map_session_id:
            return {"session_id": "", "formula_ids": [], "formulas": [], "relationships": []}
        session = self.map_sessions.get(map_session_id)
        formula_ids = [
            formula_id
            for formula_id in session.get("formula_ids", [])
            if any(node.id == formula_id for node in self.repository.document.nodes)
        ]
        formula_id_set = set(formula_ids)
        formulas = []
        for formula_id in formula_ids:
            node = self.repository.get_formula(formula_id)
            formulas.append(
                {
                    "local_formula_id": node.id,
                    "name": node.name,
                    "latex": node.latex,
                    "topic_tags": node.topic_tags,
                    "summary": node.ai_module.summary,
                }
            )
        relationships = [
            {
                "local_formula_id": edge.source_id,
                "related_formula_id": edge.target_id,
                "relation": edge.relation.value,
                "rationale": edge.rationale,
            }
            for edge in self.repository.document.edges
            if edge.verification_status in ACTIVE_EDGE_STATUSES
            and edge.source_id in formula_id_set
            and edge.target_id in formula_id_set
        ]
        return {
            "session_id": map_session_id,
            "formula_ids": formula_ids,
            "formulas": formulas,
            "relationships": relationships,
        }

    def list_map_sessions(self) -> dict[str, Any]:
        if not self.map_sessions.list():
            self.map_sessions.create(
                name="Main map",
                formula_ids=[node.id for node in self.repository.list_formulas()],
            )
        return {
            "sessions": [
                self._map_session_summary(session)
                for session in self.map_sessions.list()
            ],
            "revision": self.revision,
        }

    def create_map_session(self, name: str) -> dict[str, Any]:
        session = self.map_sessions.create(name=name)
        return self._map_session(session)

    def get_map_session(self, session_id: str) -> dict[str, Any]:
        return self._map_session(self.map_sessions.get(session_id))

    def update_map_session(
        self,
        session_id: str,
        *,
        name: str | None = None,
        pinned: bool | None = None,
    ) -> dict[str, Any]:
        return self._map_session(
            self.map_sessions.update(session_id, name=name, pinned=pinned)
        )

    def delete_map_session(self, session_id: str) -> dict[str, Any]:
        self.map_sessions.get(session_id)
        self.map_sessions.delete(session_id)
        return {"deleted": True, "session_id": session_id}

    def add_formula_to_map_session(
        self,
        session_id: str,
        formula_ref: str,
    ) -> dict[str, Any]:
        node = self.resolve_formula(formula_ref)
        session, added = self.map_sessions.add_formula(session_id, node.id)
        return {**self._map_session(session), "added": added}

    def get_map_graph(self, session_id: str) -> dict[str, Any]:
        session = self.map_sessions.get(session_id)
        node_ids = [
            formula_id for formula_id in session["formula_ids"]
            if any(node.id == formula_id for node in self.repository.document.nodes)
        ]
        nodes = [
            self._formula_summary(self.repository.get_formula(formula_id))
            for formula_id in node_ids
        ]
        node_id_set = set(node_ids)
        edges = [
            self._edge_payload(edge)
            for edge in self.repository.document.edges
            if edge.verification_status in ACTIVE_EDGE_STATUSES
            and edge.source_id in node_id_set
            and edge.target_id in node_id_set
        ]
        return {
            "session_id": session_id,
            "root_id": node_ids[0] if node_ids else None,
            "nodes": nodes,
            "edges": edges,
            "revision": self.revision,
        }

    def delete_formula(self, formula_ref: str) -> dict[str, Any]:
        node = self.resolve_formula(formula_ref)
        removed_from = self.map_sessions.remove_formula(node.id)
        self.repository.delete_formula(node.id)
        self.repository.save()
        return {
            "deleted": True,
            "formula_id": node.id,
            "removed_from_maps": removed_from,
            "revision": self.revision,
        }

    def list_deep_dive_sessions(self, formula_ref: str) -> list[dict[str, Any]]:
        node = self.resolve_formula(formula_ref)
        return self.deep_dive_sessions.list(node.id)

    def create_deep_dive_session(self, formula_ref: str) -> dict[str, Any]:
        node = self.resolve_formula(formula_ref)

        card = self._formula_card(node)
        gateway = self._require_ai_gateway()
        generated = gateway.deep_dive(
            self._formula_context(node),
            card["sources"],
        )
        sources = self._merge_sources(card["sources"], generated.get("sources", []))
        return self.deep_dive_sessions.create(
            node.id,
            {
                "title": generated["title"],
                "article": generated["article"],
                "sources": sources,
                "warnings": generated["warnings"],
            },
        )

    def get_deep_dive_session(self, formula_ref: str, session_id: str) -> dict[str, Any]:
        node = self.resolve_formula(formula_ref)
        return self.deep_dive_sessions.get(node.id, session_id)

    def delete_deep_dive_session(self, formula_ref: str, session_id: str) -> dict[str, Any]:
        node = self.resolve_formula(formula_ref)
        self.deep_dive_sessions.delete(node.id, session_id)
        return {"deleted": True, "formula_id": node.id, "session_id": session_id}

    def chat_deep_dive(
        self,
        formula_ref: str,
        session_id: str,
        message: str,
    ) -> dict[str, Any]:
        node = self.resolve_formula(formula_ref)
        message = validate_bounded_text(message, "message", max_length=MAX_SESSION_MESSAGE_LENGTH)
        session = self.deep_dive_sessions.get(node.id, session_id)
        messages = list(session.get("messages", []))
        messages.append({"role": "user", "content": message})
        reply = self._require_ai_gateway().chat(
            self._formula_context(node),
            {"title": session["title"], "article": session["article"], "sources": session["sources"]},
            messages[-20:],
        )
        reply = validate_bounded_text(reply, "reply", max_length=MAX_SESSION_REPLY_LENGTH)
        session = self.deep_dive_sessions.append_message(node.id, session_id, "user", message)
        session = self.deep_dive_sessions.append_message(node.id, session_id, "assistant", reply)
        return {"reply": reply, "session": session}

    def list_relationship_deep_dive_sessions(self, edge_id: str) -> list[dict[str, Any]]:
        self.repository.get_edge(edge_id)
        return self.deep_dive_sessions.list(self._relationship_session_key(edge_id))

    def create_relationship_deep_dive_session(self, edge_id: str) -> dict[str, Any]:
        edge = self.repository.get_edge(edge_id)
        relationship = self._relationship_context(edge)
        sources = self._relationship_sources(edge)
        gateway = self._require_ai_gateway()
        try:
            generated = gateway.deep_dive_relationship(relationship, sources)
        except SynthesisError:
            if edge.created_by != "manual":
                raise
            generated = self._manual_relationship_note(edge)
        manual_without_support = (
            edge.created_by == "manual"
            and not generated.get("sources")
            and not edge.sources
        )
        if manual_without_support:
            generated = self._manual_relationship_note(edge)
        merged_sources = (
            []
            if manual_without_support
            else self._merge_sources(sources, generated.get("sources", []))
        )
        return self.deep_dive_sessions.create(
            self._relationship_session_key(edge.id),
            {
                "title": generated["title"],
                "article": generated["article"],
                "sources": merged_sources,
                "warnings": generated["warnings"],
            },
        )

    def get_relationship_deep_dive_session(
        self,
        edge_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        self.repository.get_edge(edge_id)
        return self.deep_dive_sessions.get(
            self._relationship_session_key(edge_id),
            session_id,
        )

    def delete_relationship_deep_dive_session(
        self,
        edge_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        self.repository.get_edge(edge_id)
        self.deep_dive_sessions.delete(
            self._relationship_session_key(edge_id),
            session_id,
        )
        return {"deleted": True, "edge_id": edge_id, "session_id": session_id}

    def chat_relationship_deep_dive(
        self,
        edge_id: str,
        session_id: str,
        message: str,
    ) -> dict[str, Any]:
        edge = self.repository.get_edge(edge_id)
        message = validate_bounded_text(
            message,
            "message",
            max_length=MAX_SESSION_MESSAGE_LENGTH,
        )
        owner_id = self._relationship_session_key(edge.id)
        session = self.deep_dive_sessions.get(owner_id, session_id)
        messages = list(session.get("messages", []))
        messages.append({"role": "user", "content": message})
        reply = self._require_ai_gateway().chat(
            self._relationship_context(edge),
            {
                "title": session["title"],
                "article": session["article"],
                "sources": session["sources"],
            },
            messages[-20:],
        )
        reply = validate_bounded_text(
            reply,
            "reply",
            max_length=MAX_SESSION_REPLY_LENGTH,
        )
        session = self.deep_dive_sessions.append_message(
            owner_id,
            session_id,
            "user",
            message,
        )
        session = self.deep_dive_sessions.append_message(
            owner_id,
            session_id,
            "assistant",
            reply,
        )
        return {"reply": reply, "session": session}

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

    def _map_session_summary(self, session: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": session["id"],
            "name": session["name"],
            "pinned": bool(session["pinned"]),
            "formula_count": len(session["formula_ids"]),
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
        }

    def _map_session(self, session: dict[str, Any]) -> dict[str, Any]:
        formula_ids = set(session["formula_ids"])
        formulas = [
            self._formula_summary(node)
            for node in self.repository.list_formulas()
            if node.id in formula_ids
        ]
        return {
            **self._map_session_summary(session),
            "formula_ids": list(session["formula_ids"]),
            "formulas": formulas,
            "revision": self.revision,
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

    def _formula_context(self, node: FormulaNode) -> dict[str, Any]:
        ai_module = node.ai_module
        return {
            "id": node.id,
            "name": node.name,
            "latex": node.latex,
            "aliases": node.aliases,
            "topic_tags": node.topic_tags,
            "ai_module": {
                "summary": ai_module.summary,
                "explanation": ai_module.explanation,
                "derivation_steps": ai_module.derivation_steps,
            },
        }

    def _relationship_context(self, edge: DependencyEdge) -> dict[str, Any]:
        source = self.repository.get_formula(edge.source_id)
        target = self.repository.get_formula(edge.target_id)
        return {
            "id": edge.id,
            "source_formula": self._formula_context(source),
            "target_formula": self._formula_context(target),
            "relation": edge.relation.value,
            "rationale": edge.rationale,
            "created_by": edge.created_by,
            "verification_status": edge.verification_status.value,
            "evidence_status": edge.evidence_status.value,
        }

    def _relationship_sources(self, edge: DependencyEdge) -> list[dict[str, Any]]:
        source_ids = list(edge.sources)
        for formula_id in (edge.source_id, edge.target_id):
            node = self.repository.get_formula(formula_id)
            source_ids.extend(node.sources)
        sources = []
        seen = set()
        for source_id in source_ids:
            if source_id in seen:
                continue
            seen.add(source_id)
            sources.append(self.repository.get_source(source_id).to_dict())
        return sources

    @staticmethod
    def _relationship_session_key(edge_id: str) -> str:
        return f"relationship:{edge_id}"

    @staticmethod
    def _manual_relationship_note(edge: DependencyEdge) -> dict[str, Any]:
        introduction = edge.rationale or (
            "No explanation was provided for this relationship, and no independent "
            "web source was found."
        )
        return {
            "title": "Your relationship note",
            "article": {
                "introduction": introduction,
                "sections": [],
            },
            "sources": [],
            "warnings": [
                "No independent web source was found, so this session preserves only your explanation."
            ],
        }

    def _require_ai_gateway(self) -> DeepDiveGateway:
        if self.ai_gateway is not None:
            return self.ai_gateway
        config = self.gateway_store.load()
        if not config.ai_configured:
            raise ValidationError("AI provider is not configured")
        self.ai_gateway = ProviderGateway(config)
        return self.ai_gateway

    def _validate_manual_relationship(
        self,
        *,
        source: FormulaNode,
        target: FormulaNode,
        relation: EdgeRelation,
        rationale: str,
        source_ids: list[str],
    ) -> tuple[list[str], EdgeEvidence]:
        merged_source_ids = list(dict.fromkeys(source_ids))
        fallback = (
            EdgeEvidence.SUPPORTED
            if merged_source_ids
            else EdgeEvidence.UNVERIFIED
        )
        gateway = self.ai_gateway
        if gateway is None:
            try:
                gateway = self._require_ai_gateway()
            except (SynthesisError, ValidationError):
                gateway = None
        validate_relationship = getattr(gateway, "validate_relationship", None)
        if not callable(validate_relationship):
            return merged_source_ids, fallback

        relationship = {
            "source_formula": self._formula_context(source),
            "target_formula": self._formula_context(target),
            "relation": relation.value,
            "rationale": rationale,
            "created_by": "manual",
        }
        try:
            validation = validate_relationship(relationship, [])
        except (SynthesisError, ValidationError):
            return merged_source_ids, fallback
        if not isinstance(validation, dict):
            return merged_source_ids, fallback

        validation_sources = validation.get("sources", [])
        stored_sources = (
            self._store_relationship_validation_sources(validation_sources)
            if validation.get("web_supported") or validation_sources
            else []
        )
        merged_source_ids.extend(source.id for source in stored_sources)
        merged_source_ids = list(dict.fromkeys(merged_source_ids))
        supported = (
            bool(merged_source_ids)
            or bool(validation.get("explanation_is_reasonable"))
            or bool(validation.get("web_supported"))
        )
        return (
            merged_source_ids,
            EdgeEvidence.SUPPORTED if supported else EdgeEvidence.UNVERIFIED,
        )

    def _store_relationship_validation_sources(
        self,
        sources: Any,
    ) -> list[SourceRecord]:
        if not isinstance(sources, list):
            return []
        records = []
        for item in sources[:10]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            publisher = str(item.get("publisher") or "").strip()
            excerpt = str(item.get("excerpt") or "").strip()
            if not title or not url or not publisher:
                continue
            source_id = f"source_{hashlib.sha256(url.encode()).hexdigest()[:16]}"
            records.append(
                self.repository.add_or_update_source(
                    SourceRecord(
                        id=source_id,
                        title=title[:300],
                        url=url,
                        publisher=publisher[:120],
                        retrieved_at=utc_now(),
                        excerpt=(excerpt or "Relationship validation reference.")[:2_000],
                    )
                )
            )
        return records

    @staticmethod
    def _merge_sources(
        existing: list[dict[str, Any]],
        generated: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged = []
        seen = set()
        for source in [*existing, *generated]:
            url = str(source.get("url", "")).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append(
                {
                    "title": str(source.get("title", "")).strip() or url,
                    "url": url,
                    "publisher": str(source.get("publisher", "")).strip() or "Reference",
                }
            )
        return merged[:10]

    @staticmethod
    def _validate_chat_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
        if not isinstance(history, list) or len(history) > 20:
            raise ValidationError("history must contain at most 20 messages")
        messages = []
        for index, item in enumerate(history):
            if not isinstance(item, dict):
                raise ValidationError(f"history[{index}] must be an object")
            role = item.get("role")
            content = item.get("content")
            if role not in {"user", "assistant"} or not isinstance(content, str):
                raise ValidationError(f"history[{index}] is invalid")
            messages.append(
                {
                    "role": role,
                    "content": validate_bounded_text(
                        content,
                        f"history[{index}].content",
                        max_length=4_000,
                    ),
                }
            )
        return messages

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
            "created_by": edge.created_by,
            "evidence_status": edge.evidence_status.value,
            "confirmed_by_evidence": edge.evidence_status == EdgeEvidence.SUPPORTED,
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
            provider="deepseek" if settings.openai_api_key else "",
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
    return MathernetService(
        repository,
        agent,
        gateway_store,
        synthesizer if isinstance(synthesizer, ProviderGateway) else None,
        deep_dive_sessions=DeepDiveSessionStore(
            settings.search_cache_path.parent / "deep_dive_sessions.json"
        ),
        formula_introductions=FormulaIntroductionStore(
            settings.search_cache_path.parent / "formula_introductions.json"
        ),
        map_sessions=MapSessionStore(
            settings.search_cache_path.parent / "map_sessions.json"
        ),
    )
