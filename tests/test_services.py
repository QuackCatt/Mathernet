import tempfile
import unittest
from pathlib import Path

from mathernet.errors import ConflictError
from mathernet.models import AIModule, SourceRecord
from mathernet.repository import GraphRepository
from mathernet.services import MathernetService


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = GraphRepository(Path(self.temporary.name) / "graph.json")
        self.repository.add_or_update_source(
            SourceRecord(
                "src_service",
                "Service source",
                "https://example.edu/service",
                "Example University",
                "2026-10-12T00:00:00+00:00",
                "Verified source excerpt",
            )
        )
        self.first = self.repository.add_formula(
            formula_id="formula_first",
            name="First formula",
            latex="a=b",
            aliases=["first"],
            topic_tags=["algebra"],
            ai_module=AIModule("AI summary", "AI explanation"),
            sources=["src_service"],
        )
        self.second = self.repository.add_formula(
            formula_id="formula_second",
            name="Second formula",
            latex="c=d",
            aliases=["second"],
            topic_tags=["algebra"],
            ai_module=AIModule("AI summary", "AI explanation"),
            sources=["src_service"],
        )
        self.repository.save()
        self.service = MathernetService(self.repository)

    def tearDown(self):
        self.temporary.cleanup()

    def test_formula_card_graph_and_filters_share_revision(self):
        edge = self.repository.add_edge(
            edge_id="edge_service",
            source_id=self.first.id,
            target_id=self.second.id,
            relation="prerequisite",
            rationale="The first formula is a prerequisite.",
            sources=["src_service"],
        )
        self.repository.save()

        card = self.service.get_formula_card(self.second.id)
        self.assertTrue(card["incoming_edges"][0]["requires_user_confirmation"])
        self.assertFalse(card["incoming_edges"][0]["accepted"])
        self.assertEqual(edge.id, card["incoming_edges"][0]["id"])

        graph = self.service.get_graph(self.first.id, depth=1)
        self.assertEqual({item["id"] for item in graph["nodes"]}, {"formula_first", "formula_second"})
        listed = self.service.list_formulas(query="second", topic="algebra")
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["revision"], graph["revision"])

    def test_confirmation_persists_and_old_versions_conflict(self):
        edge = self.repository.add_edge(
            edge_id="edge_service",
            source_id=self.first.id,
            target_id=self.second.id,
            relation="prerequisite",
            rationale="The first formula is a prerequisite.",
            sources=["src_service"],
        )
        self.repository.save()
        old_version = edge.updated_at

        confirmed = self.service.confirm_edge(edge.id, expected_updated_at=old_version)
        self.assertTrue(confirmed["accepted"])
        self.assertFalse(confirmed["requires_user_confirmation"])

        reloaded = GraphRepository(Path(self.temporary.name) / "graph.json")
        self.assertEqual(
            reloaded.get_edge(edge.id).verification_status.value,
            "user_verified",
        )
        with self.assertRaises(ConflictError):
            self.service.confirm_edge(edge.id, expected_updated_at="older-version")

    def test_user_module_is_separate_from_ai_module(self):
        original_ai = self.first.ai_module.to_dict()
        card = self.service.update_user_module(self.first.id, "My reflection")
        self.assertEqual(card["formula"]["ai_module"], original_ai)
        self.assertEqual(card["formula"]["user_module"]["notes"], "My reflection")


if __name__ == "__main__":
    unittest.main()
