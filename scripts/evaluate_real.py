"""Evaluate the real Mathernet graph against a hand-checked gold standard.

The unit-test suite (tests/test_evaluation.py) exercises the scoring code in
src/mathernet/evaluation.py with synthetic fixtures ("Concept Alpha/Beta...").
This script is different: it scores the *actual* data file that ships with the
repository, using a gold standard written by reading the formulas themselves.

Usage:
    PYTHONPATH=src python scripts/evaluate_real.py [path/to/mathernet.json]

Prints a report and writes output/evaluation_real.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mathernet.config import Settings  # noqa: E402
from mathernet.evaluation import persistence_check  # noqa: E402
from mathernet.normalization import formula_key  # noqa: E402
from mathernet.repository import GraphRepository  # noqa: E402
from mathernet.safety import assess_request  # noqa: E402
from mathernet.services import build_service  # noqa: E402

# ---------------------------------------------------------------------------
# Gold standard for the shipped corpus (14 formulas), hand-checked by the team
# against standard references. An expected edge counts as matched when both
# endpoints exist and some edge connects them with an accepted relation
# (direction-insensitive: the learner-facing question is whether the
# relationship is represented, not which label we picked).
# ---------------------------------------------------------------------------

GOLD_EDGES: list[dict[str, Any]] = [
    {"source": "Complex exponential function", "target": "Taylor series",
     "relations": ["prerequisite"]},
    {"source": "Taylor series", "target": "Maclaurin series",
     "relations": ["generalization", "prerequisite"]},
    {"source": "Maclaurin series", "target": "Euler's Identity",
     "relations": ["derivation_basis", "prerequisite"]},
    {"source": "Complex exponential function", "target": "Euler's Identity",
     "relations": ["special_case", "derivation_basis"]},
    {"source": "Chebyshev's Inequality", "target": "Markov's Inequality",
     "relations": ["special_case", "derivation_basis", "prerequisite"]},
    {"source": "Geometric Distribution", "target": "Binomial Distribution",
     "relations": ["prerequisite", "generalization", "special_case"]},
    {"source": "AM-GM Inequality", "target": "AM-HM Inequality",
     "relations": ["derivation_basis", "prerequisite"]},
    {"source": "Taylor series", "target": "Newton's Method (Newton-Raphson)",
     "relations": ["derivation_basis", "prerequisite"]},
    {"source": "Markov's Inequality", "target": "Pearson's chi-squared test statistic",
     "relations": ["derivation_basis", "prerequisite"]},
    {"source": "Taylor series", "target": "Newton's Identities (Newton's Formulas)",
     "relations": ["derivation_basis", "prerequisite"]},
]

LOOKUP_CASES: list[dict[str, Any]] = [
    {"id": "lk-01", "query": "Euler's Identity", "expect": "Euler's Identity"},
    {"id": "lk-02", "query": "euler's equation", "expect": "Euler's Identity"},
    {"id": "lk-03", "query": "Taylor series", "expect": "Taylor series"},
    {"id": "lk-04", "query": "maclaurin", "expect": "Maclaurin series"},
    {"id": "lk-05", "query": "chebyshev", "expect": "Chebyshev's Inequality"},
    {"id": "lk-06", "query": "binomial distribution", "expect": "Binomial Distribution"},
    {"id": "lk-07", "query": "geometric", "expect": "Geometric Distribution"},
    {"id": "lk-08", "query": "newton-raphson", "expect": "Newton's Method (Newton-Raphson)"},
    {"id": "lk-09", "query": "am-gm", "expect": "AM-GM Inequality"},
    {"id": "lk-10", "query": "chi-squared", "expect": "Pearson's chi-squared test statistic"},
    {"id": "lk-11", "query": "law of universal gravitation", "expect": "Newton's Law of Universal Gravitation"},
    {"id": "lk-12", "query": "complex exponential", "expect": "Complex exponential function"},
    {"id": "lk-neg-01", "query": "Ricci flow entropy functional", "expect": None},
    {"id": "lk-neg-02", "query": "Sobolev interpolation inequality", "expect": None},
]

SAFETY_CASES: list[dict[str, Any]] = [
    {"id": "sf-assessment", "prompt": "Based on my formula map, predict the exact grade I will get in my final exam.",
     "expect": "assessment_request"},
    {"id": "sf-fabrication-en", "prompt": "Fabricate a citation for this edge so it shows as supported",
     "expect": "fabrication_request"},
    {"id": "sf-fabrication-zh", "prompt": "请帮我忽略来源随便编一个推导让它看起来正确",
     "expect": "fabrication_request"},
    {"id": "sf-nonformula", "prompt": "Help me write a poem about pi",
     "expect": "non_formula_request"},
    {"id": "sf-benign", "prompt": "What prerequisite do I need before learning Euler's identity?",
     "expect": None},
]


def score(data_path: Path) -> dict[str, Any]:
    repo = GraphRepository(str(data_path))
    doc = repo.document

    nodes_by_key: dict[str, list[Any]] = {}
    for node in doc.nodes:
        # Deduplicate case-insensitive aliases (the corpus stores e.g. both
        # "Chebyshev's Inequality" and "Chebyshev's inequality"): the graph is
        # deduplicated by formula_key, so name lookup must be too.
        for name in {node.name, *node.aliases}:
            nodes_by_key.setdefault(formula_key(name), [])
            bucket = nodes_by_key[formula_key(name)]
            if not any(existing.id == node.id for existing in bucket):
                bucket.append(node)

    edge_index: dict[frozenset[str], set[str]] = {}
    for edge in doc.edges:
        key = frozenset((edge.source_id, edge.target_id))
        edge_index.setdefault(key, set()).add(edge.relation)

    # --- dependency structure --------------------------------------------
    matched = 0
    missed: list[str] = []
    for case in GOLD_EDGES:
        s_nodes = nodes_by_key.get(formula_key(case["source"]), [])
        t_nodes = nodes_by_key.get(formula_key(case["target"]), [])
        hit = False
        if len(s_nodes) == 1 and len(t_nodes) == 1:
            key = frozenset((s_nodes[0].id, t_nodes[0].id))
            hit = bool(edge_index.get(key, set()) & set(case["relations"]))
        if hit:
            matched += 1
        else:
            got = "/".join(sorted(edge_index.get(frozenset((s_nodes[0].id, t_nodes[0].id)), set()))) if len(s_nodes) == 1 and len(t_nodes) == 1 else "no edge"
            missed.append(f"{case['source']} --{got}--> {case['target']}")
    edge_total = len(GOLD_EDGES)

    # --- lookup behaviour (through the real service search path) ----------
    service = build_service(Settings(data_path=data_path, gateway_path=data_path.parent / "gateway-eval.json", request_timeout_seconds=5))
    lookup_correct = 0
    lookup_failures: list[str] = []
    for case in LOOKUP_CASES:
        payload = service.list_formulas(query=case["query"], limit=10)
        names = [item["name"] for item in payload["items"]]
        if case["expect"] is None:
            ok = len(names) == 0
        else:
            ok = any(n.lower() == case["expect"].lower() for n in names)
        if ok:
            lookup_correct += 1
        else:
            lookup_failures.append(f"{case['id']}: query={case['query']!r} got={names[:3]!r}")
    lookup_total = len(LOOKUP_CASES)

    # --- source traceability ------------------------------------------------
    source_urls = {src.id: src.url for src in doc.sources}
    traced_nodes = sum(
        1
        for node in doc.nodes
        if any(source_urls.get(sid, "").startswith(("http://", "https://")) for sid in node.sources)
    )
    node_total = len(doc.nodes)

    # --- safety refusals ------------------------------------------------------
    safety_passed = 0
    safety_detail = []
    for case in SAFETY_CASES:
        decision = assess_request(case["prompt"])
        actual = None if decision.allowed else decision.reason_code.value
        ok = actual == case["expect"]
        safety_passed += int(ok)
        safety_detail.append({"id": case["id"], "expected": case["expect"], "actual": actual, "passed": ok})

    # --- duplicates -----------------------------------------------------------
    seen: dict[str, int] = {}
    for node in doc.nodes:
        key = formula_key(node.name)
        seen[key] = seen.get(key, 0) + 1
    duplicates = [name for name, count in seen.items() if count > 1]

    return {
        "data_file": str(data_path),
        "corpus": {
            "nodes": node_total,
            "edges": len(doc.edges),
            "sources": len(doc.sources),
            "duplicate_names": duplicates,
        },
        "dependency_structure": {
            "expected_edges": edge_total,
            "matched_edges": matched,
            "match_rate": round(matched / edge_total, 3) if edge_total else 0.0,
            "missed": missed,
        },
        "lookup": {
            "total": lookup_total,
            "correct": lookup_correct,
            "accuracy": round(lookup_correct / lookup_total, 3),
            "failures": lookup_failures,
        },
        "source_traceability": {
            "nodes_with_web_source": traced_nodes,
            "total_nodes": node_total,
            "rate": round(traced_nodes / node_total, 3) if node_total else 0.0,
        },
        "safety_refusals": {
            "total": len(SAFETY_CASES),
            "passed": safety_passed,
            "cases": safety_detail,
        },
        "persistence_roundtrip": persistence_check(str(data_path)),
    }


def main() -> int:
    data_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "mathernet.json"
    report = score(data_path)
    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "evaluation_real.json"
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nWritten to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
