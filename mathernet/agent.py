from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .errors import RefusalError, SynthesisError, ValidationError
from .llm import Synthesizer, SynthesisDependency, SynthesisResult
from .models import (
    DependencyEdge,
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
    unresolved_dependencies: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class FormulaAgent:
    def __init__(
        self,
        repository: GraphRepository,
        search_provider: SearchProvider,
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

    def learn(self, query: str) -> LearnResult:
        enforce_request_safety(query)
        existing = self.repository.find_formula(query)
        if existing is not None:
            return LearnResult(node=existing, created=False)

        if hasattr(self.search_provider, "__enter__"):
            with self.search_provider as provider:
                raw_results = provider.search(query, limit=5)
        else:
            raw_results = self.search_provider.search(query, limit=5)
        results = filter_approved_sources(raw_results, self.approved_publishers)
        if not results:
            raise RefusalError(
                "Mathernet found no reliable approved source for this formula, so it will not invent an explanation.",
                RefusalReason.NO_RELIABLE_SOURCE.value,
            )

        synthesis = self.synthesizer.synthesize(query, results)
        source_records = self._validate_and_store_sources(synthesis, results)
        formula_id = stable_id("formula", formula_key(query))
        node = self.repository.add_formula(
            formula_id=formula_id,
            name=synthesis.name or query,
            latex=synthesis.latex,
            aliases=[query, *synthesis.aliases],
            topic_tags=synthesis.topic_tags,
            ai_module=synthesis.ai_module,
            sources=[source.id for source in source_records],
        )
        edges, unresolved = self._resolve_dependencies(
            node, synthesis.dependencies, source_records
        )
        warnings = list(synthesis.warnings)
        if unresolved:
            warnings.append(
                "Some suggested prerequisites are not in the local library; create those cards first, then add the edges explicitly."
            )
        self.repository.save()
        return LearnResult(
            node=node,
            created=True,
            edges=edges,
            unresolved_dependencies=unresolved,
            warnings=warnings,
        )

    def _validate_and_store_sources(
        self, synthesis: SynthesisResult, results: list[SearchResult]
    ) -> list[SourceRecord]:
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
    ) -> tuple[list[DependencyEdge], list[str]]:
        valid_sources = {source.id: source.url for source in source_records}
        edges: list[DependencyEdge] = []
        unresolved: list[str] = []
        for dependency in dependencies:
            prerequisite = self.repository.find_formula(dependency.prerequisite_name)
            if prerequisite is None:
                unresolved.append(dependency.prerequisite_name)
                continue
            if prerequisite.id == target.id:
                continue
            source_ids = [
                source_id
                for source_id, url in valid_sources.items()
                if url in dependency.source_urls
            ]
            if not source_ids:
                unresolved.append(dependency.prerequisite_name)
                continue
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
                )
            except ValidationError:
                continue
            edges.append(edge)
        return edges, unresolved


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"
