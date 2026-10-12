import unittest

from mathernet.errors import ValidationError
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
from mathernet.rules import (
    validate_edge_transition,
    validate_graph_rules,
    validate_identifier,
)


def source():
    return SourceRecord(
        "src_rule",
        "Rule source",
        "https://example.edu/rules",
        "Example University",
        "2026-10-12T00:00:00+00:00",
        "Authoritative rule excerpt",
    )


def node(identifier, name, aliases=None):
    return FormulaNode(
        id=identifier,
        name=name,
        latex=rf"\text{{{name}}}",
        aliases=aliases or [],
        topic_tags=["mathematics"],
        ai_module=AIModule("summary", "explanation"),
        user_module=UserModule(updated_at="2026-10-12T00:00:00+00:00"),
        status=FormulaStatus.NEW,
        sources=["src_rule"],
        created_at="2026-10-12T00:00:00+00:00",
        updated_at="2026-10-12T00:00:00+00:00",
    )


def edge(identifier, source_id, target_id, relation, status):
    return DependencyEdge(
        id=identifier,
        source_id=source_id,
        target_id=target_id,
        relation=relation,
        rationale="Source-backed relation",
        sources=["src_rule"],
        verification_status=status,
        created_at="2026-10-12T00:00:00+00:00",
        updated_at="2026-10-12T00:00:00+00:00",
    )


class RulesTests(unittest.TestCase):
    def test_identifier_rejects_unsafe_values(self):
        with self.assertRaises(ValidationError):
            validate_identifier("../secret", "id")

    def test_formula_identity_collisions_are_rejected(self):
        document = GraphDocument(
            nodes=[
                node("formula_a", "Quadratic formula"),
                node("formula_b", "Another formula", ["quadratic formula"]),
            ],
            sources=[source()],
        )
        with self.assertRaises(ValidationError):
            validate_graph_rules(document)

    def test_prerequisite_cycles_are_rejected(self):
        document = GraphDocument(
            nodes=[node("formula_a", "Formula A"), node("formula_b", "Formula B")],
            edges=[
                edge(
                    "edge_a_b",
                    "formula_a",
                    "formula_b",
                    EdgeRelation.PREREQUISITE,
                    VerificationStatus.AI_SUGGESTED,
                ),
                edge(
                    "edge_b_a",
                    "formula_b",
                    "formula_a",
                    EdgeRelation.DERIVATION_BASIS,
                    VerificationStatus.USER_VERIFIED,
                ),
            ],
            sources=[source()],
        )
        with self.assertRaises(ValidationError):
            validate_graph_rules(document)

    def test_equivalent_form_cycle_is_allowed(self):
        document = GraphDocument(
            nodes=[node("formula_a", "Formula A"), node("formula_b", "Formula B")],
            edges=[
                edge(
                    "edge_a_b",
                    "formula_a",
                    "formula_b",
                    EdgeRelation.EQUIVALENT_FORM,
                    VerificationStatus.USER_VERIFIED,
                ),
                edge(
                    "edge_b_a",
                    "formula_b",
                    "formula_a",
                    EdgeRelation.EQUIVALENT_FORM,
                    VerificationStatus.USER_VERIFIED,
                ),
            ],
            sources=[source()],
        )
        validate_graph_rules(document)

    def test_edge_status_transition_is_explicit(self):
        validate_edge_transition(
            VerificationStatus.AI_SUGGESTED,
            VerificationStatus.USER_VERIFIED,
        )
        with self.assertRaises(ValidationError):
            validate_edge_transition(
                VerificationStatus.REJECTED,
                VerificationStatus.USER_VERIFIED,
            )


if __name__ == "__main__":
    unittest.main()
