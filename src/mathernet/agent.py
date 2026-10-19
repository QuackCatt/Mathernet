from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .agent_skills import (
    KNOWN_RELATIONSHIP_RULES,
    FormulaCandidate,
    FormulaDiscovery,
)
from .errors import NotFoundError, RefusalError, SynthesisError, ValidationError
from .llm import Synthesizer, SynthesisDependency, SynthesisResult
from .models import (
    DependencyEdge,
    EdgeEvidence,
    EdgeRelation,
    FormulaNode,
    RefusalReason,
    SourceRecord,
)
from .normalization import formula_key
from .repository import GraphRepository
from .retrieval import SearchProvider, SearchResult, filter_approved_sources
from .safety import enforce_request_safety


@dataclass(slots=True)
class LearnResult:
    node: FormulaNode
    created: bool
    edges: list[DependencyEdge] = field(default_factory=list)


class FormulaAgent:
    def __init__(
        self,
        repository: GraphRepository,
        search_provider: SearchProvider | None,
        synthesizer: Synthesizer,
        approved_publishers: tuple[str, ...],
    ):
        self.repository = repository
        self.search_provider = search_provider
        self.synthesizer = synthesizer
        self.approved_publishers = approved_publishers

    def lookup(self, query: str) -> FormulaNode | None:
        enforce_request_safety(query)
        return self.repository.find_formula(query)

    def discover_formula_candidates(self, query: str) -> list[FormulaCandidate]:
        enforce_request_safety(query)
        discover_candidates = getattr(
            self.synthesizer,
            "discover_formula_candidates",
            None,
        )
        if not callable(discover_candidates):
            raise SynthesisError("AI formula candidate search is not configured")
        catalog = [
            {
                "id": node.id,
                "name": node.name,
                "aliases": node.aliases,
                "latex": node.latex,
            }
            for node in self.repository.list_formulas()
        ]
        candidates = discover_candidates(query, catalog)
        if not isinstance(candidates, list):
            raise SynthesisError("AI formula candidate search returned an invalid result")
        resolved = []
        for candidate in candidates[:5]:
            if not isinstance(candidate, FormulaCandidate):
                continue
            local_match = None
            if candidate.local_formula_id:
                try:
                    local_match = self.repository.get_formula(candidate.local_formula_id)
                except NotFoundError:
                    local_match = None
            if local_match is None:
                local_match = self.repository.find_formula(candidate.canonical_name)
            candidate.local_formula_id = local_match.id if local_match else ""
            resolved.append(candidate)
        if not resolved:
            raise SynthesisError("AI formula candidate search returned no usable candidates")
        return resolved

    def learn(
        self,
        query: str,
        map_context: dict | None = None,
        selected_candidate: FormulaCandidate | None = None,
    ) -> LearnResult:
        enforce_request_safety(query)
        existing = None
        if selected_candidate and selected_candidate.local_formula_id:
            try:
                existing = self.repository.get_formula(selected_candidate.local_formula_id)
            except NotFoundError:
                existing = None
        if existing is None:
            lookup_name = (
                selected_candidate.canonical_name if selected_candidate else query
            )
            existing = self.repository.find_formula(lookup_name)
        if existing is not None:
            return LearnResult(node=existing, created=False)

        if selected_candidate is not None:
            canonical_query = selected_candidate.canonical_name
            discovered = None
            discovery = FormulaDiscovery(
                canonical_name=selected_candidate.canonical_name,
                local_formula_id=selected_candidate.local_formula_id,
                aliases=[selected_candidate.canonical_name],
                confidence=selected_candidate.confidence,
                reason=selected_candidate.reason,
            )
        else:
            canonical_query, discovered, discovery = self._discover_formula(query)
        if discovered is not None:
            return LearnResult(node=discovered, created=False)

        direct_mode = self.search_provider is None
        if direct_mode:
            raw_results = []
        else:
            if hasattr(self.search_provider, "__enter__"):
                with self.search_provider as provider:
                    raw_results = provider.search(canonical_query, limit=5)
            else:
                raw_results = self.search_provider.search(canonical_query, limit=5)
        results = filter_approved_sources(raw_results, self.approved_publishers)
        if not direct_mode and not results:
            raise RefusalError(
                "Mathernet found no reliable approved source for this formula, so it will not invent an explanation.",
                RefusalReason.NO_RELIABLE_SOURCE.value,
            )

        synthesis_context = dict(map_context) if map_context else {}
        if selected_candidate is not None:
            synthesis_context["selected_candidate"] = selected_candidate.to_dict()
        if synthesis_context:
            synthesis = self.synthesizer.synthesize(
                canonical_query,
                results,
                synthesis_context,
            )
        else:
            synthesis = self.synthesizer.synthesize(canonical_query, results)
        if selected_candidate is not None:
            synthesis.name = selected_candidate.canonical_name
            synthesis.latex = selected_candidate.latex
            synthesis.topic_tags = list(
                dict.fromkeys(
                    [
                        selected_candidate.topic,
                        *(synthesis.topic_tags if synthesis.topic_tags else []),
                    ]
                )
            )
            if not synthesis.ai_module.summary:
                synthesis.ai_module.summary = selected_candidate.summary
        duplicate = self._find_synthesized_duplicate(synthesis, canonical_query)
        if duplicate is not None:
            return LearnResult(node=duplicate, created=False)
        synthesis.dependencies = self._merge_known_relationships(
            synthesis.name or canonical_query,
            synthesis.dependencies,
            map_context,
        )

        citation_results = synthesis.sources if direct_mode else results
        if direct_mode and not citation_results:
            synthesis.ai_module.derivation_steps = []
        source_records = self._validate_and_store_sources(synthesis, citation_results)
        formula_id = stable_id("formula", formula_key(synthesis.name or canonical_query))
        node = self.repository.add_formula(
            formula_id=formula_id,
            name=synthesis.name or canonical_query,
            latex=synthesis.latex,
            aliases=_unique_aliases(
                query,
                canonical_query,
                *(discovery.aliases if discovery else ()),
                *synthesis.aliases,
            ),
            topic_tags=synthesis.topic_tags,
            ai_module=synthesis.ai_module,
            sources=[source.id for source in source_records],
        )
        edges, _ = self._resolve_dependencies(
            node,
            synthesis.dependencies,
            source_records,
            set((map_context or {}).get("formula_ids", [])),
        )
        self.repository.save()
        return LearnResult(
            node=node,
            created=True,
            edges=edges,
        )

    @staticmethod
    def _merge_known_relationships(
        target_name: str,
        dependencies: list[SynthesisDependency],
        map_context: dict | None,
    ) -> list[SynthesisDependency]:
        if not map_context:
            return dependencies
        target_key = formula_key(target_name)
        known_by_target = {
            formula_key(target): (
                source,
                relation,
                rationale,
            )
            for source, target, relation, rationale in KNOWN_RELATIONSHIP_RULES
        }
        rule = known_by_target.get(target_key)
        if rule is None:
            return dependencies
        source_name, relation_value, rationale = rule
        source_key = formula_key(source_name)
        local_source = next(
            (
                item
                for item in map_context.get("formulas", [])
                if formula_key(str(item.get("name", ""))) == source_key
                or formula_key(str(item.get("local_formula_id", ""))) == source_key
            ),
            None,
        )
        if local_source is None:
            return dependencies
        local_formula_id = str(local_source.get("local_formula_id", "")).strip()
        if not local_formula_id:
            return dependencies
        merged = list(dependencies)
        existing = {
            (dependency.local_formula_id, dependency.relation.value)
            for dependency in merged
        }
        relation = EdgeRelation(relation_value)
        if (local_formula_id, relation.value) not in existing:
            merged.append(
                SynthesisDependency(
                    prerequisite_name=str(local_source.get("name") or source_name),
                    relation=relation,
                    rationale=rationale,
                    source_urls=[],
                    local_formula_id=local_formula_id,
                    confidence=1.0,
                )
            )
        return merged

    def _discover_formula(
        self,
        query: str,
    ) -> tuple[str, FormulaNode | None, FormulaDiscovery | None]:
        discover = getattr(self.synthesizer, "discover_formula", None)
        if not callable(discover):
            return query, None, None
        catalog = [
            {
                "id": node.id,
                "name": node.name,
                "aliases": node.aliases,
                "latex": node.latex,
            }
            for node in self.repository.list_formulas()
        ]
        try:
            discovery = discover(query, catalog)
        except SynthesisError:
            return query, None, None
        if not isinstance(discovery, FormulaDiscovery):
            return query, None, None
        if discovery.local_formula_id:
            try:
                return (
                    discovery.canonical_name or query,
                    self.repository.get_formula(discovery.local_formula_id),
                    discovery,
                )
            except NotFoundError:
                pass
        if discovery.canonical_name:
            match = self.repository.find_formula(discovery.canonical_name)
            if match is not None:
                return discovery.canonical_name, match, discovery
        return discovery.canonical_name or query, None, discovery

    def _find_synthesized_duplicate(
        self,
        synthesis: SynthesisResult,
        canonical_query: str,
    ) -> FormulaNode | None:
        for candidate in (synthesis.name, canonical_query, *synthesis.aliases):
            if not candidate:
                continue
            match = self.repository.find_formula(candidate)
            if match is not None:
                return match
        return None

    def _validate_and_store_sources(
        self, synthesis: SynthesisResult, results: list[SearchResult]
    ) -> list[SourceRecord]:
        if not results:
            for dependency in synthesis.dependencies:
                dependency.source_urls = []
            return []
        allowed_urls = {result.url for result in results}
        cited_urls = {
            url
            for dependency in synthesis.dependencies
            for url in dependency.source_urls
        }
        unsupported = cited_urls - allowed_urls
        if unsupported:
            raise SynthesisError(
                "language model cited URLs that were not returned by retrieval: "
                + ", ".join(sorted(unsupported))
            )
        records = [result.to_source_record() for result in results]
        return [self.repository.add_or_update_source(record) for record in records]

    def _resolve_dependencies(
        self,
        target: FormulaNode,
        dependencies: list[SynthesisDependency],
        source_records: list[SourceRecord],
        map_formula_ids: set[str],
    ) -> tuple[list[DependencyEdge], list[str]]:
        valid_sources = {source.id: source.url for source in source_records}
        edges: list[DependencyEdge] = []
        unresolved: list[str] = []
        for dependency in dependencies:
            prerequisite = None
            if dependency.local_formula_id:
                try:
                    prerequisite = self.repository.get_formula(dependency.local_formula_id)
                except NotFoundError:
                    prerequisite = None
            if prerequisite is None:
                prerequisite = self.repository.find_formula(dependency.prerequisite_name)
            if prerequisite is None:
                unresolved.append(dependency.prerequisite_name)
                continue
            if prerequisite.id == target.id or (
                map_formula_ids and prerequisite.id not in map_formula_ids
            ):
                continue
            source_ids = [
                source_id
                for source_id, url in valid_sources.items()
                if url in dependency.source_urls
            ]
            edge_id = self.repository.unique_edge_id(
                stable_id(
                    "edge",
                    prerequisite.id,
                    target.id,
                    dependency.relation.value,
                    dependency.rationale,
                )
            )
            try:
                edge = self.repository.add_edge(
                    edge_id=edge_id,
                    source_id=prerequisite.id,
                    target_id=target.id,
                    relation=dependency.relation,
                    rationale=dependency.rationale,
                    sources=source_ids,
                    evidence_status=(
                        EdgeEvidence.SUPPORTED
                        if source_ids
                        else EdgeEvidence.UNVERIFIED
                    ),
                )
            except ValidationError:
                continue
            edges.append(edge)
        return edges, unresolved


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _unique_aliases(*values: str) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        key = formula_key(normalized)
        if not normalized or key in seen:
            continue
        seen.add(key)
        aliases.append(normalized)
    return aliases
