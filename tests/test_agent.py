import tempfile
import unittest
from pathlib import Path

from mathernet.agent import FormulaAgent
from mathernet.agent_skills import FormulaCandidate, FormulaDiscovery
from mathernet.llm import SynthesisDependency, SynthesisResult
from mathernet.models import AIModule, EdgeRelation, SearchResult, VerificationStatus
from mathernet.repository import GraphRepository


def result_for(name, latex, dependency=None):
    dependencies = []
    if dependency is not None:
        dependencies.append(dependency)
    return SynthesisResult(
        name=name,
        latex=latex,
        aliases=[],
        topic_tags=["algebra"],
        ai_module=AIModule("summary"),
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


class DiscoveryCountingSynthesizer(StubSynthesizer):
    def __init__(self, result=None):
        super().__init__(result)
        self.discovery_calls = 0

    def discover_formula(self, query, library):
        self.discovery_calls += 1
        return FormulaDiscovery(canonical_name="A different formula")


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = GraphRepository(Path(self.temporary.name) / "graph.json")
        self.source = SearchResult(
            "Model source",
            "https://example.edu/formula",
            "Example University",
            "A model-supplied excerpt",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_local_hit_skips_synthesis(self):
        source_record = self.source.to_source_record()
        self.repository.add_or_update_source(source_record)
        self.repository.add_formula(
            formula_id="formula_existing",
            name="Existing formula",
            latex="x=1",
            aliases=["existing"],
            topic_tags=["algebra"],
            ai_module=AIModule("summary"),
            sources=[source_record.id],
        )
        synthesizer = StubSynthesizer()
        agent = FormulaAgent(self.repository, synthesizer)
        result = agent.learn("existing")
        self.assertFalse(result.created)
        self.assertEqual(synthesizer.calls, 0)

    def test_model_sources_are_stored_without_external_verification(self):
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
        agent = FormulaAgent(self.repository, synthesizer)
        learned = agent.learn("Cited formula")
        self.assertEqual(len(learned.node.sources), 1)
        self.assertEqual(
            self.repository.get_source(learned.node.sources[0]).url,
            "https://example.edu/cited",
        )

    def test_invalid_source_urls_are_dropped_instead_of_failing_the_card(self):
        result = result_for("Unsafe citation", "x=2")
        result.sources = [
            SearchResult("Unsafe", "javascript:alert(1)", "Unknown", "A bad excerpt")
        ]
        agent = FormulaAgent(self.repository, StubSynthesizer(result))
        learned = agent.learn("Unsafe citation")
        self.assertEqual(learned.node.sources, [])

    def test_selected_candidate_skips_discovery_and_preserves_formula_identity(self):
        selected = FormulaCandidate(
            canonical_name="Selected formula",
            latex="y=x^2",
            summary="The selected candidate summary.",
            topic="calculus",
            reason="Exact candidate selected by the learner.",
            confidence=0.94,
        )
        synthesizer = DiscoveryCountingSynthesizer(
            result_for("A different formula", "y=x")
        )
        agent = FormulaAgent(self.repository, synthesizer)

        learned = agent.learn("selected formula", selected_candidate=selected)

        self.assertEqual(synthesizer.discovery_calls, 0)
        self.assertEqual(synthesizer.calls, 1)
        self.assertEqual(
            synthesizer.map_context["selected_candidate"],
            selected.to_dict(),
        )
        self.assertEqual(learned.node.name, "Selected formula")
        self.assertEqual(learned.node.latex, "y=x^2")
        self.assertEqual(learned.node.topic_tags[0], "calculus")

    def test_successful_card_creates_ai_suggested_edge(self):
        source_record = self.source.to_source_record()
        self.repository.add_or_update_source(source_record)
        self.repository.add_formula(
            formula_id="formula_prereq",
            name="Prerequisite formula",
            latex="a=b",
            aliases=["prerequisite"],
            topic_tags=["algebra"],
            ai_module=AIModule("summary"),
            sources=[source_record.id],
        )
        dependency = SynthesisDependency(
            "Prerequisite formula",
            EdgeRelation.PREREQUISITE,
            "Model-supplied rationale",
            [self.source.url],
        )
        synthesis = result_for("Target formula", "c=d", dependency)
        synthesis.sources = [self.source]
        agent = FormulaAgent(self.repository, StubSynthesizer(synthesis))
        result = agent.learn("Target formula")
        self.assertTrue(result.created)
        self.assertEqual(len(result.edges), 1)
        self.assertEqual(result.edges[0].verification_status, VerificationStatus.AI_SUGGESTED)
        self.assertEqual(result.edges[0].evidence_status.value, "supported")

    def test_new_card_compares_every_formula_in_the_active_map(self):
        source_record = self.source.to_source_record()
        self.repository.add_or_update_source(source_record)
        self.repository.add_formula(
            formula_id="formula_distribution",
            name="Distribution formula",
            latex="X \\sim F",
            aliases=["distribution"],
            topic_tags=["probability", "distribution"],
            ai_module=AIModule("summary"),
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
        agent = FormulaAgent(self.repository, synthesizer)
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
        source_record = self.source.to_source_record()
        self.repository.add_or_update_source(source_record)
        self.repository.add_formula(
            formula_id="formula_expectation",
            name="expectation",
            latex=r"\mathbb{E}[X]",
            aliases=["expected value"],
            topic_tags=["probability", "distribution"],
            ai_module=AIModule("summary"),
            sources=[source_record.id],
        )
        synthesizer = StubSynthesizer(result_for("variance", r"\operatorname{Var}(X)"))
        agent = FormulaAgent(self.repository, synthesizer)
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


if __name__ == "__main__":
    unittest.main()
