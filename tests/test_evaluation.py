import unittest

from mathernet.evaluation import evaluate_graph
from mathernet.models import (
    AIModule,
    DependencyEdge,
    EdgeRelation,
    FormulaNode,
    FormulaStatus,
    GraphDocument,
    SourceRecord,
    UserModule,
    VerificationStatus,
)
from mathernet.normalization import formula_key
from tests.test_data import gold_cases

class EvaluationTests(unittest.TestCase):
    def test_complete_gold_graph_passes_all_metrics(self):
        gold = gold_cases()
        source = SourceRecord(
            "src_gold",
            "Authoritative source",
            "https://example.edu/gold",
            "Example University",
            "2026-10-12T00:00:00+00:00",
            "Verified excerpt",
        )
        names: dict[str, FormulaNode] = {}
        aliases: dict[str, set[str]] = {}
        canonical_names: dict[str, str] = {}
        for case in gold["lookup_cases"]:
            key = formula_key(case["expected_name"])
            canonical_names.setdefault(key, case["expected_name"])
            aliases.setdefault(key, set()).add(case["query"])
        for case in gold["dependency_chains"]:
            for name in case["formulas"]:
                key = formula_key(name)
                canonical_names.setdefault(key, name)
                aliases.setdefault(key, set())
        for index, (key, name_aliases) in enumerate(sorted(aliases.items())):
            name = canonical_names[key]
            node = FormulaNode(
                id=f"formula_{index}",
                name=name,
                latex=rf"\text{{{name}}}",
                aliases=sorted(name_aliases),
                topic_tags=["mathematics"],
                ai_module=AIModule("summary"),
                user_module=UserModule(updated_at="2026-10-12T00:00:00+00:00"),
                status=FormulaStatus.NEW,
                sources=["src_gold"],
                created_at="2026-10-12T00:00:00+00:00",
                updated_at="2026-10-12T00:00:00+00:00",
            )
            names[key] = node
        edges = []
        edge_index = 0
        for case in gold["dependency_chains"]:
            for source_name, target_name in case["expected_edges"]:
                edges.append(
                    DependencyEdge(
                        id=f"edge_{edge_index}",
                        source_id=names[formula_key(source_name)].id,
                        target_id=names[formula_key(target_name)].id,
                        relation=EdgeRelation.PREREQUISITE,
                        rationale="Gold-standard rationale",
                        sources=["src_gold"],
                        verification_status=VerificationStatus.AI_SUGGESTED,
                        created_at="2026-10-12T00:00:00+00:00",
                        updated_at="2026-10-12T00:00:00+00:00",
                    )
                )
                edge_index += 1
        document = GraphDocument(nodes=list(names.values()), edges=edges, sources=[source])
        report = evaluate_graph(document, gold, persistence_pass=True)
        self.assertTrue(report.overall_pass)
        self.assertEqual(report.edge_matches, report.expected_edges)
        self.assertEqual(report.lookup_correct, 10)
        self.assertEqual(report.source_cards_pass, 10)
        self.assertEqual(report.safety_pass, 4)

    def test_empty_graph_fails_acceptance_evaluation(self):
        report = evaluate_graph(
            GraphDocument(),
            gold_cases(),
            persistence_pass=True,
        )
        self.assertFalse(report.overall_pass)
        self.assertEqual(report.safety_total, 4)


if __name__ == "__main__":
    unittest.main()
