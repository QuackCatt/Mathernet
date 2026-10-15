import tempfile
import unittest
from pathlib import Path

from mathernet.agent import FormulaAgent
from mathernet.errors import RefusalError, SynthesisError
from mathernet.llm import SynthesisDependency, SynthesisResult
from mathernet.models import AIModule, EdgeRelation, RefusalReason, SourceRecord, VerificationStatus
from mathernet.repository import GraphRepository
from mathernet.retrieval import SearchResult


def result_for(name, latex, dependency=None):
    dependencies = []
    if dependency is not None:
        dependencies.append(dependency)
    return SynthesisResult(
        name=name,
        latex=latex,
        aliases=[],
        topic_tags=["algebra"],
        ai_module=AIModule("summary", "explanation"),
        dependencies=dependencies,
    )


class StubSynthesizer:
    def __init__(self, result=None):
        self.result = result
        self.calls = 0
        self.map_context = None

    def synthesize(self, query, sources, map_context=None):
        self.calls += 1
        self.map_context = map_context
        if self.result is None:
            raise AssertionError("synthesis must not run")
        return self.result


class StubSearchProvider:
    def __init__(self, results):
        self.results = results

    def search(self, query, limit=5):
        return self.results


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = GraphRepository(Path(self.temporary.name) / "graph.json")
        self.source = SearchResult(
            "Trusted formula source",
            "https://example.edu/formula",
            "Example University",
            "A reliable excerpt",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_local_hit_skips_retrieval_and_synthesis(self):
        self.repository.add_or_update_source(self.source.to_source_record())
        self.repository.add_formula(
            formula_id="formula_existing",
            name="Existing formula",
            latex="x=1",
            aliases=["existing"],
            topic_tags=["algebra"],
            ai_module=AIModule("summary", "explanation"),
            sources=["src_" + self.source.to_source_record().id.removeprefix("src_")],
        )
        synthesizer = StubSynthesizer()
        agent = FormulaAgent(self.repository, StubSearchProvider([]), synthesizer, ("Example University",))
        result = agent.learn("existing")
        self.assertFalse(result.created)
        self.assertEqual(synthesizer.calls, 0)

    def test_no_reliable_source_refuses_without_synthesis(self):
        synthesizer = StubSynthesizer()
        agent = FormulaAgent(self.repository, StubSearchProvider([]), synthesizer, ("Example University",))
        with self.assertRaises(RefusalError) as context:
            agent.learn("Unsupported formula")
        self.assertEqual(context.exception.reason_code, RefusalReason.NO_RELIABLE_SOURCE.value)
        self.assertEqual(synthesizer.calls, 0)

    def test_direct_ai_mode_creates_an_uncited_answer_without_fake_sources(self):
        result = result_for("Direct formula", "x=1")
        result.ai_module.derivation_steps = ["Unsupported derivation"]
        result.dependencies = [
            SynthesisDependency(
                "Existing formula",
                EdgeRelation.PREREQUISITE,
                "unsupported",
                ["https://example.edu/invented"],
            )
        ]
        synthesizer = StubSynthesizer(result)
        agent = FormulaAgent(self.repository, None, synthesizer, ())
        learned = agent.learn("Direct formula")
        self.assertTrue(learned.created)
        self.assertEqual(synthesizer.calls, 1)
        self.assertEqual(learned.node.sources, [])
        self.assertEqual(learned.node.ai_module.derivation_steps, [])
        self.assertEqual(learned.edges, [])
        self.assertTrue(any("without source citations" in warning for warning in learned.warnings))

    def test_direct_ai_mode_keeps_real_citations_returned_by_the_model(self):
        result = result_for("Cited formula", "x=2")
        result.sources = [
            SearchResult(
                "AI cited source",
                "https://example.edu/cited",
                "Example University",
                "A cited excerpt",
            )
        ]
        synthesizer = StubSynthesizer(result)
        agent = FormulaAgent(self.repository, None, synthesizer, ())
        learned = agent.learn("Cited formula")
        self.assertEqual(len(learned.node.sources), 1)
        self.assertEqual(len(learned.node.ai_module.derivation_steps), 0)

    def test_successful_card_creates_ai_suggested_edge(self):
        self.repository.add_or_update_source(self.source.to_source_record())
        self.repository.add_formula(
            formula_id="formula_prereq",
            name="Prerequisite formula",
            latex="a=b",
            aliases=["prerequisite"],
            topic_tags=["algebra"],
            ai_module=AIModule("summary", "explanation"),
            sources=[self.source.to_source_record().id],
        )
        dependency = SynthesisDependency(
            "Prerequisite formula",
            EdgeRelation.PREREQUISITE,
            "Supported rationale",
            [self.source.url],
        )
        synthesis = result_for("Target formula", "c=d", dependency)
        agent = FormulaAgent(
            self.repository,
            StubSearchProvider([self.source]),
            StubSynthesizer(synthesis),
            ("Example University",),
        )
        result = agent.learn("Target formula")
        self.assertTrue(result.created)
        self.assertEqual(len(result.edges), 1)
        self.assertEqual(result.edges[0].verification_status, VerificationStatus.AI_SUGGESTED)

    def test_new_card_compares_every_formula_in_the_active_map(self):
        self.repository.add_or_update_source(self.source.to_source_record())
        source_record = self.source.to_source_record()
        self.repository.add_formula(
            formula_id="formula_distribution",
            name="Distribution formula",
            latex="X \\sim F",
            aliases=["distribution"],
            topic_tags=["probability", "distribution"],
            ai_module=AIModule("summary", "explanation"),
            sources=[source_record.id],
        )
        dependency = SynthesisDependency(
            "Distribution formula",
            EdgeRelation.SPECIAL_CASE,
            "The requested distribution is a named special case.",
            [],
            local_formula_id="formula_distribution",
            confidence=0.94,
        )
        synthesizer = StubSynthesizer(result_for("Special distribution", "X \\sim F_0", dependency))
        agent = FormulaAgent(
            self.repository,
            StubSearchProvider([self.source]),
            synthesizer,
            ("Example University",),
        )
        map_context = {
            "session_id": "map_test",
            "formula_ids": ["formula_distribution"],
            "formulas": [{"local_formula_id": "formula_distribution"}],
            "relationships": [],
        }
        result = agent.learn("special distribution", map_context)
        self.assertEqual(synthesizer.map_context, map_context)
        self.assertEqual(len(result.edges), 1)
        self.assertEqual(result.edges[0].source_id, "formula_distribution")
        self.assertEqual(result.edges[0].relation, EdgeRelation.SPECIAL_CASE)

    def test_known_distribution_chain_gets_a_relationship_guardrail(self):
        self.repository.add_or_update_source(self.source.to_source_record())
        source_record = self.source.to_source_record()
        self.repository.add_formula(
            formula_id="formula_expectation",
            name="expectation",
            latex=r"\mathbb{E}[X]",
            aliases=["expected value"],
            topic_tags=["probability", "distribution"],
            ai_module=AIModule("summary", "explanation"),
            sources=[source_record.id],
        )
        synthesizer = StubSynthesizer(result_for("variance", r"\operatorname{Var}(X)"))
        agent = FormulaAgent(
            self.repository,
            StubSearchProvider([self.source]),
            synthesizer,
            ("Example University",),
        )
        result = agent.learn(
            "variance",
            {
                "session_id": "map_distribution",
                "formula_ids": ["formula_expectation"],
                "formulas": [
                    {
                        "local_formula_id": "formula_expectation",
                        "name": "expectation",
                    }
                ],
                "relationships": [],
            },
        )
        self.assertEqual(len(result.edges), 1)
        self.assertEqual(result.edges[0].source_id, "formula_expectation")
        self.assertEqual(result.edges[0].relation, EdgeRelation.PREREQUISITE)

    def test_model_cannot_cite_an_unseen_url(self):
        dependency = SynthesisDependency(
            "Prerequisite formula",
            EdgeRelation.PREREQUISITE,
            "Unsupported rationale",
            ["https://evil.example/fabricated"],
        )
        synthesis = result_for("Target formula", "c=d", dependency)
        agent = FormulaAgent(
            self.repository,
            StubSearchProvider([self.source]),
            StubSynthesizer(synthesis),
            ("Example University",),
        )
        with self.assertRaises(SynthesisError):
            agent.learn("Target formula")
        self.assertEqual(len(self.repository.document.nodes), 0)


if __name__ == "__main__":
    unittest.main()
