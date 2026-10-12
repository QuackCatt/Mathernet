import json
import tempfile
import unittest
from pathlib import Path

from mathernet.agent import FormulaAgent
from mathernet.llm import SynthesisResult
from mathernet.models import AIModule, GraphDocument
from mathernet.repository import GraphRepository
from mathernet.retrieval import SearchResult, StaticSearchProvider
from mathernet.storage import JsonGraphStore


ROOT = Path(__file__).resolve().parents[1]
GOLD = json.loads((ROOT / "tests" / "gold_cases.json").read_text(encoding="utf-8"))
DEMO = json.loads((ROOT / "examples" / "demo_graph.json").read_text(encoding="utf-8"))


class GoldSynthesizer:
    def __init__(self, expected_name):
        self.expected_name = expected_name

    def synthesize(self, query, sources):
        return SynthesisResult(
            name=self.expected_name,
            latex=r"\text{" + self.expected_name.replace("}", "") + "}",
            aliases=[query],
            topic_tags=["mathematics"],
            ai_module=AIModule(
                f"Source-backed overview of {self.expected_name}.",
                f"Explanation preserved from {len(sources)} retrieved source(s).",
            ),
            dependencies=[],
        )


def run_lookup_cases(repository):
    evaluated = []
    for case in GOLD["lookup_cases"]:
        existing = repository.find_formula(case["query"])
        if existing is None:
            source = SearchResult(
                f"{case['expected_name']} source",
                f"https://example.edu/{case['id']}",
                "Example University",
                f"Authoritative excerpt for {case['expected_name']}.",
            )
            agent = FormulaAgent(
                repository,
                StaticSearchProvider([source]),
                GoldSynthesizer(case["expected_name"]),
                ("Example University",),
            )
            result = agent.learn(case["query"])
            existing = result.node
        evaluated.append((case, existing))
    return evaluated


class GoldSuiteTests(unittest.TestCase):
    def test_dependency_chain_gold_table(self):
        cases = GOLD["dependency_chains"]
        self.assertEqual(len(cases), 10)
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertGreaterEqual(len(case["formulas"]), 2)
                self.assertGreaterEqual(case["authority_source_count"], 2)
                possible_pairs = max(1, len(case["formulas"]) - 1)
                achieved_ratio = len(case["expected_edges"]) / possible_pairs
                self.assertGreaterEqual(achieved_ratio, 0.8)
                for source, target in case["expected_edges"]:
                    self.assertIn(source, case["formulas"])
                    self.assertIn(target, case["formulas"])

    def test_lookup_and_deduplication_gold_table(self):
        cases = GOLD["lookup_cases"]
        self.assertEqual(len(cases), 10)
        self.assertEqual(sum(1 for case in cases if case["existing"]), 5)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph.json"
            JsonGraphStore(path).save(GraphDocument.from_dict(DEMO))
            repository = GraphRepository(path)
            evaluated = run_lookup_cases(repository)
            self.assertEqual(len(evaluated), 10)
            for case, node in evaluated:
                with self.subTest(case=case["id"]):
                    self.assertIsNotNone(node)
                    self.assertEqual(node.name, case["expected_name"])
                    self.assertGreaterEqual(len(node.sources), case["expected_source_count"])
                    if not case["existing"]:
                        self.assertIsNotNone(repository.find_formula(case["query"]))

    def test_source_traceability_for_ten_generated_cards(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph.json"
            JsonGraphStore(path).save(GraphDocument.from_dict(DEMO))
            repository = GraphRepository(path)
            evaluated = run_lookup_cases(repository)
        self.assertEqual(len(evaluated), 10)
        source_ids = {source.id for source in repository.document.sources}
        for _, node in evaluated:
            with self.subTest(node=node.id):
                self.assertTrue(node.sources)
                self.assertTrue(set(node.sources).issubset(source_ids))
                self.assertTrue(node.ai_module.summary)
                self.assertTrue(node.ai_module.explanation)
                for step in node.ai_module.derivation_steps:
                    self.assertTrue(step)
                    self.assertTrue(node.sources)
        for source in repository.document.sources:
            with self.subTest(source=source.id):
                self.assertTrue(source.title)
                self.assertTrue(source.url.startswith("http"))

    def test_safety_cases_cover_four_failure_modes(self):
        cases = GOLD["safety_cases"]
        self.assertEqual(len(cases), 4)
        self.assertEqual(
            {case["expected_reason"] for case in cases},
            {"assessment_request", "non_formula_request", "no_reliable_source", "fabrication_request"},
        )

    def test_dual_modules_survive_two_restarts(self):
        self.assertEqual(len(GOLD["persistence_assertions"]), 4)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph.json"
            JsonGraphStore(path).save(GraphDocument.from_dict(DEMO))
            original = GraphRepository(path).get_formula("formula_euler_identity")
            original_ai = original.ai_module.to_dict()
            original_user = original.user_module.to_dict()
            original_status = original.status.value
            for _ in range(2):
                repository = GraphRepository(path)
                loaded = repository.get_formula("formula_euler_identity")
                repository.save()
            self.assertEqual(loaded.ai_module.to_dict(), original_ai)
            self.assertEqual(loaded.user_module.to_dict(), original_user)
            self.assertEqual(loaded.status.value, original_status)


if __name__ == "__main__":
    unittest.main()
