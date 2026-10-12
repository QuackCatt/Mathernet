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

    def synthesize(self, query, sources):
        self.calls += 1
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
