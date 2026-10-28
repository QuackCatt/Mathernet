from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import GraphDocument, VerificationStatus
from .normalization import formula_key
from .safety import assess_request
from .storage import JsonGraphStore


@dataclass(slots=True)
class EvaluationReport:
    edge_matches: int
    expected_edges: int
    edge_match_rate: float
    edge_threshold_pass: bool
    lookup_correct: int
    lookup_total: int
    lookup_accuracy: float
    lookup_threshold_pass: bool
    deduplication_pass: bool
    source_cards_pass: int
    source_cards_total: int
    source_traceability_pass: bool
    safety_pass: int
    safety_total: int
    safety_pass_complete: bool
    persistence_pass: bool
    overall_pass: bool
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_gold_cases(path: Path | str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"could not load gold cases from {path}: {error}") from error
    if not isinstance(data, dict):
        raise ValueError("gold cases must be a JSON object")
    return data


def evaluate_graph(
    document: GraphDocument,
    gold_cases: dict[str, Any],
    *,
    persistence_pass: bool = True,
) -> EvaluationReport:
    nodes_by_name: dict[str, list[Any]] = {}
    for node in document.nodes:
        names = {formula_key(node.name), *(formula_key(alias) for alias in node.aliases)}
        for name in names:
            nodes_by_name.setdefault(name, []).append(node)
    source_ids = {source.id for source in document.sources}
    node_by_id = {node.id: node for node in document.nodes}

    edge_details = []
    matched_edges = 0
    expected_edge_pairs: list[tuple[str, str]] = []
    for case in gold_cases.get("dependency_chains", []):
        for source_name, target_name in case.get("expected_edges", []):
            expected_edge_pairs.append((source_name, target_name))
            source_matches = nodes_by_name.get(formula_key(source_name), [])
            target_matches = nodes_by_name.get(formula_key(target_name), [])
            matched = False
            if len(source_matches) == 1 and len(target_matches) == 1:
                source = source_matches[0]
                target = target_matches[0]
                matched = any(
                    edge.source_id == source.id
                    and edge.target_id == target.id
                    and edge.verification_status
                    in {
                        VerificationStatus.AI_SUGGESTED,
                        VerificationStatus.USER_VERIFIED,
                        VerificationStatus.USER_EDITED,
                    }
                    and bool(edge.rationale)
                    and bool(edge.sources)
                    and set(edge.sources).issubset(source_ids)
                    for edge in document.edges
                )
            matched_edges += int(matched)
            edge_details.append(
                {
                    "case_id": case.get("id"),
                    "source": source_name,
                    "target": target_name,
                    "matched": matched,
                }
            )
    expected_edges = len(expected_edge_pairs)
    edge_match_rate = matched_edges / expected_edges if expected_edges else 0.0

    lookup_details = []
    lookup_correct = 0
    deduplication_pass = True
    source_cards_pass = 0
    lookup_cases = gold_cases.get("lookup_cases", [])
    for case in lookup_cases:
        query = case["query"]
        matches = nodes_by_name.get(formula_key(query), [])
        unique_match = len(matches) == 1
        node = matches[0] if unique_match else None
        correct = bool(
            node and formula_key(node.name) == formula_key(case["expected_name"])
        )
        lookup_correct += int(correct)
        if case.get("existing") and not unique_match:
            deduplication_pass = False
        card_pass = False
        if node:
            sources = [source for source in document.sources if source.id in node.sources]
            card_pass = (
                bool(node.sources)
                and set(node.sources).issubset(source_ids)
                and len(sources) == len(node.sources)
                and all(
                    source.title
                    and source.url.startswith(("http://", "https://"))
                    and source.publisher
                    and source.retrieved_at
                    and source.excerpt
                    for source in sources
                )
            )
        source_cards_pass += int(card_pass)
        lookup_details.append(
            {
                "case_id": case["id"],
                "query": query,
                "found": node.id if node else None,
                "correct": correct,
                "source_card_pass": card_pass,
                "match_count": len(matches),
            }
        )
    lookup_total = len(lookup_cases)
    lookup_accuracy = lookup_correct / lookup_total if lookup_total else 0.0

    safety_details = []
    safety_pass = 0
    safety_cases = gold_cases.get("safety_cases", [])
    for case in safety_cases:
        decision = assess_request(case["request"])
        if decision.allowed:
            passed = not case.get("source_available", True)
            actual_reason = "no_reliable_source" if passed else "allowed"
        else:
            actual_reason = decision.reason_code.value
            passed = actual_reason == case["expected_reason"]
        safety_pass += int(passed)
        safety_details.append(
            {
                "case_id": case["id"],
                "expected": case["expected_reason"],
                "actual": actual_reason,
                "passed": passed,
            }
        )

    source_traceability_pass = (
        source_cards_pass == lookup_total and lookup_total > 0
    )
    edge_threshold_pass = edge_match_rate >= 0.8 and expected_edges > 0
    lookup_threshold_pass = lookup_accuracy >= 0.9 and lookup_total == 10
    safety_total = len(safety_cases)
    safety_pass_complete = safety_pass == safety_total and safety_total == 4
    overall_pass = all(
        (
            edge_threshold_pass,
            lookup_threshold_pass,
            deduplication_pass,
            source_traceability_pass,
            safety_pass_complete,
            persistence_pass,
        )
    )
    return EvaluationReport(
        edge_matches=matched_edges,
        expected_edges=expected_edges,
        edge_match_rate=edge_match_rate,
        edge_threshold_pass=edge_threshold_pass,
        lookup_correct=lookup_correct,
        lookup_total=lookup_total,
        lookup_accuracy=lookup_accuracy,
        lookup_threshold_pass=lookup_threshold_pass,
        deduplication_pass=deduplication_pass,
        source_cards_pass=source_cards_pass,
        source_cards_total=lookup_total,
        source_traceability_pass=source_traceability_pass,
        safety_pass=safety_pass,
        safety_total=safety_total,
        safety_pass_complete=safety_pass_complete,
        persistence_pass=persistence_pass,
        overall_pass=overall_pass,
        details={
            "dependency_edges": edge_details,
            "lookups": lookup_details,
            "safety": safety_details,
        },
    )


def persistence_check(path: Path | str) -> bool:
    store = JsonGraphStore(path)
    first = store.load().to_dict()
    second = store.load().to_dict()
    return first == second and all(
        "ai_module" in node and "user_module" in node for node in first["nodes"]
    )
