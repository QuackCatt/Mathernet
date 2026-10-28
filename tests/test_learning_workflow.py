import tempfile
import unittest
from pathlib import Path

from mathernet.agent import FormulaAgent
from mathernet.api import handle_api_request
from mathernet.gateway import GatewayStore
from mathernet.llm import SynthesisResult
from mathernet.models import AIModule, SearchResult
from mathernet.repository import GraphRepository
from mathernet.services import MathernetService


class StubSynthesizer:
    def synthesize(self, query, sources, map_context=None):
        return SynthesisResult(
            name=query,
            latex="x=1",
            aliases=[],
            topic_tags=["mathematics"],
            ai_module=AIModule(f"A compact summary of {query}."),
            sources=[
                SearchResult(
                    "Synthetic reference",
                    "https://example.edu/synthetic",
                    "Example University",
                    "Synthetic excerpt.",
                )
            ],
        )


def build_test_service(root: Path) -> MathernetService:
    repository = GraphRepository(root / "graph.json")
    return MathernetService(
        repository,
        FormulaAgent(repository, StubSynthesizer()),
        GatewayStore(root / "gateway.json"),
    )


class LearningWorkflowTests(unittest.TestCase):
    def test_learning_creates_and_reuses_a_persistent_card(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = build_test_service(root)

            created = handle_api_request(
                service,
                "POST",
                "/api/learn",
                {"query": "synthetic concept"},
            )
            self.assertEqual(created.status, 201)
            self.assertTrue(created.payload["created"])
            self.assertEqual(
                created.payload["formula"]["formula"]["name"],
                "synthetic concept",
            )
            self.assertEqual(len(created.payload["formula"]["sources"]), 1)

            reused = handle_api_request(
                service,
                "POST",
                "/api/learn",
                {"query": "synthetic concept"},
            )
            self.assertEqual(reused.status, 200)
            self.assertFalse(reused.payload["created"])

            persisted = build_test_service(root).get_formula_card("synthetic concept")
            self.assertEqual(
                persisted["formula"]["ai_module"]["summary"],
                created.payload["formula"]["formula"]["ai_module"]["summary"],
            )


if __name__ == "__main__":
    unittest.main()
