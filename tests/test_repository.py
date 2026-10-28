import tempfile
import unittest
from pathlib import Path

from mathernet.models import (
    AIModule,
    EdgeEvidence,
    EdgeRelation,
    FormulaStatus,
    SourceRecord,
    VerificationStatus,
)
from mathernet.repository import GraphRepository


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "graph.json"
        self.repository = GraphRepository(self.path)
        self.repository.add_or_update_source(
            SourceRecord(
                "src_one",
                "Source",
                "https://example.com/source",
                "Example University",
                "2026-10-12T00:00:00+00:00",
                "Source excerpt",
            )
        )

    def tearDown(self):
        self.temporary.cleanup()

    def add_formula(self, formula_id, name, alias):
        return self.repository.add_formula(
            formula_id=formula_id,
            name=name,
            latex=name,
            aliases=[alias],
            topic_tags=["algebra"],
            ai_module=AIModule("summary"),
            sources=["src_one"],
        )

    def test_alias_lookup_prevents_duplicates(self):
        self.add_formula("formula_a", "Quadratic formula", "abc formula")
        self.assertTrue(self.repository.find_formula("ABC Formula"))
        with self.assertRaises(Exception):
            self.add_formula("formula_b", "Different name", "abc formula")

    def test_edge_lifecycle_and_references(self):
        self.add_formula("formula_a", "Prerequisite", "pre")
        self.add_formula("formula_b", "Target", "target")
        edge = self.repository.add_edge(
            edge_id="edge_a",
            source_id="formula_a",
            target_id="formula_b",
            relation=EdgeRelation.PREREQUISITE,
            rationale="supported rationale",
            sources=["src_one"],
        )
        self.assertEqual(edge.verification_status, VerificationStatus.AI_SUGGESTED)
        self.repository.save()
        self.repository.reload()
        verified = self.repository.verify_edge("edge_a")
        self.repository.save()
        self.repository.reload()
        self.assertEqual(verified.verification_status, VerificationStatus.USER_VERIFIED)
        rejected = self.repository.reject_edge("edge_a")
        self.assertEqual(rejected.verification_status, VerificationStatus.REJECTED)

    def test_manual_edge_can_be_created_without_a_source(self):
        self.add_formula("formula_a", "Prerequisite", "pre")
        self.add_formula("formula_b", "Target", "target")
        edge = self.repository.add_edge(
            edge_id="edge_manual",
            source_id="formula_a",
            target_id="formula_b",
            relation=EdgeRelation.PREREQUISITE,
            rationale="",
            sources=[],
            manual=True,
        )
        self.assertEqual(edge.verification_status, VerificationStatus.USER_VERIFIED)
        self.assertEqual(edge.evidence_status, EdgeEvidence.UNVERIFIED)
        self.assertEqual(edge.sources, [])

    def test_editing_edge_to_no_sources_marks_evidence_unverified(self):
        self.add_formula("formula_a", "Prerequisite", "pre")
        self.add_formula("formula_b", "Target", "target")
        edge = self.repository.add_edge(
            edge_id="edge_edit",
            source_id="formula_a",
            target_id="formula_b",
            relation=EdgeRelation.PREREQUISITE,
            rationale="Initially cited.",
            sources=["src_one"],
        )
        self.assertEqual(edge.evidence_status, EdgeEvidence.SUPPORTED)

        updated = self.repository.edit_edge(
            edge.id,
            relation=EdgeRelation.PREREQUISITE,
            rationale="Now uncited.",
            sources=[],
        )

        self.assertEqual(updated.sources, [])
        self.assertEqual(updated.evidence_status, EdgeEvidence.UNVERIFIED)
        self.repository.save()

    def test_delete_edge_removes_only_that_relationship(self):
        first = self.add_formula("formula_a", "Prerequisite", "pre")
        second = self.add_formula("formula_b", "Target", "target")
        self.repository.add_edge(
            edge_id="edge_remove",
            source_id=first.id,
            target_id=second.id,
            relation=EdgeRelation.PREREQUISITE,
            rationale="Selected relationship.",
            sources=[],
            manual=True,
        )
        deleted = self.repository.delete_edge("edge_remove")
        self.repository.save()
        self.assertEqual(deleted.id, "edge_remove")
        self.assertEqual(self.repository.document.edges, [])

    def test_rejected_edge_can_be_proposed_again_without_id_collision(self):
        self.add_formula("formula_a", "Prerequisite", "pre")
        self.add_formula("formula_b", "Target", "target")
        self.repository.add_edge(
            edge_id="edge_retry",
            source_id="formula_a",
            target_id="formula_b",
            relation=EdgeRelation.PREREQUISITE,
            rationale="supported rationale",
            sources=["src_one"],
        )
        self.repository.reject_edge("edge_retry")
        self.repository.add_edge(
            edge_id=self.repository.unique_edge_id("edge_retry"),
            source_id="formula_a",
            target_id="formula_b",
            relation=EdgeRelation.PREREQUISITE,
            rationale="revised rationale",
            sources=["src_one"],
        )
        self.assertEqual(len(self.repository.document.edges), 2)

    def test_dual_modules_and_status_survive_restart(self):
        node = self.add_formula("formula_a", "Formula", "alias")
        self.repository.update_user_module(node.id, "personal reflection")
        self.repository.set_formula_status(node.id, FormulaStatus.LEARNING)
        self.repository.save()
        restarted = GraphRepository(self.path)
        loaded = restarted.get_formula("formula_a")
        self.assertEqual(loaded.ai_module.summary, "summary")
        self.assertEqual(loaded.user_module.notes, "personal reflection")
        self.assertEqual(loaded.status, FormulaStatus.LEARNING)

    def test_delete_formula_removes_incident_edges(self):
        first = self.add_formula("formula_a", "First", "first")
        second = self.add_formula("formula_b", "Second", "second")
        self.repository.add_edge(
            edge_id="edge_delete",
            source_id=first.id,
            target_id=second.id,
            relation=EdgeRelation.PREREQUISITE,
            rationale="supported rationale",
            sources=["src_one"],
        )

        self.repository.delete_formula(first.id)
        self.repository.save()

        restarted = GraphRepository(self.path)
        self.assertIsNone(restarted.find_formula("First"))
        self.assertEqual([edge.id for edge in restarted.document.edges], [])
        self.assertIsNotNone(restarted.get_source("src_one"))


if __name__ == "__main__":
    unittest.main()
