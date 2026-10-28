import json
import tempfile
import unittest
from pathlib import Path

from mathernet.agent_skills import ChatSafetyReview, parse_formula_deep_dive
from mathernet.api import handle_api_request, openapi_document
from mathernet.deep_dive_sessions import DeepDiveSessionStore
from mathernet.errors import NotFoundError, SynthesisError
from mathernet.formula_introductions import FormulaIntroductionStore
from mathernet.map_sessions import MapSessionStore
from mathernet.repository import GraphRepository
from mathernet.services import MathernetService
from tests.test_data import synthetic_graph_payload


ROOT = Path(__file__).resolve().parents[1]


class FakeDeepDiveGateway:
    def __init__(self):
        self.deep_dive_calls = []
        self.relationship_calls = []
        self.relationship_validation_calls = []
        self.chat_calls = []
        self.review_calls = []
        self.chat_review_allowed = True
        self.relationship_sources = [
            {
                "title": "Relationship reference",
                "url": "https://example.edu/relationship",
                "publisher": "Example University",
            }
        ]
        self.relationship_validation_sources = list(self.relationship_sources)
        self.relationship_explanation_reasonable = True
        self.relationship_web_supported = True

    def deep_dive(self, formula, sources):
        self.deep_dive_calls.append((formula, sources))
        number = len(self.deep_dive_calls)
        return {
            "title": f"Exploration {number}",
            "article": {
                "introduction": f"A durable opening article for session {number}.",
                "sections": [
                    {
                        "kind": "background",
                        "subtitle": "Background",
                        "heading": "Useful context",
                        "body": "This optional passage explains the wider setting.",
                    }
                ],
            },
            "sources": [
                {
                    "title": "Example reference",
                    "url": "https://example.edu/formula",
                    "publisher": "Example University",
                },
                {
                    "title": "Duplicate reference",
                    "url": "https://example.edu/formula",
                    "publisher": "Example University",
                },
            ],
            "warnings": ["Web sources were unavailable, so this is model-generated context."],
        }

    def chat(self, formula, deep_dive, messages):
        self.chat_calls.append((formula, deep_dive, messages))
        return "The key idea is $x=1$."

    def review_chat_response(self, formula, deep_dive, message, reply):
        self.review_calls.append((formula, deep_dive, message, reply))
        return ChatSafetyReview(
            allowed=self.chat_review_allowed,
            violation="none" if self.chat_review_allowed else "assessment_solution",
            note="Checked by the second-pass reviewer.",
        )

    def deep_dive_relationship(self, relationship, sources):
        self.relationship_calls.append((relationship, sources))
        return {
            "title": "Why these formulas connect",
            "article": {
                "introduction": "This relationship links two equivalent views of the same idea.",
                "sections": [],
            },
            "sources": list(self.relationship_sources),
            "warnings": [],
        }

    def validate_relationship(self, relationship, sources):
        self.relationship_validation_calls.append((relationship, sources))
        return {
            "explanation_is_reasonable": self.relationship_explanation_reasonable,
            "web_supported": self.relationship_web_supported,
            "assessment": "The relationship was checked against the stated explanation.",
            "sources": list(self.relationship_validation_sources)
            if self.relationship_web_supported
            else [],
        }


class DeepDiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = GraphRepository(Path(self.temporary.name) / "graph.json")
        self.repository.document = self.repository.document.from_dict(synthetic_graph_payload())
        self.repository.save()
        self.gateway = FakeDeepDiveGateway()
        self.sessions = DeepDiveSessionStore(Path(self.temporary.name) / "sessions.json")
        self.introductions = FormulaIntroductionStore(
            Path(self.temporary.name) / "introductions.json"
        )
        self.map_sessions = MapSessionStore(Path(self.temporary.name) / "map_sessions.json")
        self.service = MathernetService(
            self.repository,
            ai_gateway=self.gateway,
            deep_dive_sessions=self.sessions,
            formula_introductions=self.introductions,
            map_sessions=self.map_sessions,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_parses_article_and_drops_invalid_sources(self):
        parsed = parse_formula_deep_dive(json.dumps({
            "title": "A careful exploration",
            "introduction": "A careful introduction.",
            "sections": [
                {
                    "kind": "story",
                    "subtitle": "Story",
                    "heading": "A real account",
                    "body": "The idea developed gradually.",
                },
                {
                    "kind": "invalid",
                    "subtitle": "Invalid",
                    "heading": "Drop me",
                    "body": "Not a supported kind.",
                },
            ],
            "sources": [
                {"title": "Valid", "url": "https://example.edu/a", "publisher": "Example"},
                {"title": "Invalid", "url": "javascript:alert(1)", "publisher": "Example"},
            ],
            "warnings": [],
        }))
        self.assertEqual(parsed["article"]["introduction"], "A careful introduction.")
        self.assertEqual(parsed["article"]["sections"][0]["heading"], "A real account")
        self.assertEqual(len(parsed["article"]["sections"]), 1)
        self.assertEqual(len(parsed["sources"]), 1)
        self.assertEqual(parsed["sources"][0]["url"], "https://example.edu/a")

    def test_empty_article_is_rejected(self):
        with self.assertRaises(SynthesisError):
            parse_formula_deep_dive(json.dumps({
                "title": "Empty",
                "introduction": "",
                "sections": [],
                "sources": [],
                "warnings": [],
            }))

    def test_empty_generated_article_does_not_replace_saved_content(self):
        with self.assertRaises(SynthesisError):
            self.sessions.create(
                "formula_euler_identity",
                {
                    "title": "Empty response",
                    "article": {"introduction": "", "sections": []},
                    "sources": [],
                    "warnings": [],
                },
            )

        self.assertEqual(self.sessions.list("formula_euler_identity"), [])

    def test_sessions_are_preserved_and_new_sessions_regenerate(self):
        first = handle_api_request(
            self.service,
            "POST",
            "/api/formulas/formula_euler_identity/deep-dive/sessions",
            {},
        )
        second = handle_api_request(
            self.service,
            "POST",
            "/api/formulas/formula_euler_identity/deep-dive/sessions",
            {},
        )
        listed = handle_api_request(
            self.service,
            "GET",
            "/api/formulas/formula_euler_identity/deep-dive/sessions",
        )

        self.assertEqual(first.status, 201)
        self.assertEqual(second.status, 201)
        self.assertNotEqual(first.payload["id"], second.payload["id"])
        self.assertIn("session 1", first.payload["article"]["introduction"])
        self.assertIn("session 2", second.payload["article"]["introduction"])
        self.assertEqual(len(listed.payload["sessions"]), 2)
        self.assertEqual(len(self.gateway.deep_dive_calls), 2)
        self.assertEqual(len(first.payload["sources"]), 4)
        self.assertEqual(
            len({source["url"] for source in first.payload["sources"]}),
            len(first.payload["sources"]),
        )

        reopened = handle_api_request(
            self.service,
            "GET",
            f"/api/formulas/formula_euler_identity/deep-dive/sessions/{first.payload['id']}",
        )
        self.assertEqual(reopened.payload["article"], first.payload["article"])

    def test_chat_is_appended_to_the_selected_session(self):
        created = handle_api_request(
            self.service,
            "POST",
            "/api/formulas/formula_euler_identity/deep-dive/sessions",
            {},
        ).payload
        response = handle_api_request(
            self.service,
            "POST",
            f"/api/formulas/formula_euler_identity/deep-dive/sessions/{created['id']}/chat",
            {"message": "Why is this useful?"},
        )

        self.assertEqual(response.status, 200)
        self.assertIn("$x=1$", response.payload["reply"])
        self.assertEqual(
            [item["role"] for item in response.payload["session"]["messages"]],
            ["user", "assistant"],
        )
        self.assertEqual(self.gateway.chat_calls[0][2][-1]["role"], "user")

        persisted = self.sessions.get("formula_euler_identity", created["id"])
        self.assertEqual(len(persisted["messages"]), 2)

    def test_second_pass_review_withdraws_unsafe_reply(self):
        created = handle_api_request(
            self.service,
            "POST",
            "/api/formulas/formula_euler_identity/deep-dive/sessions",
            {},
        ).payload
        self.gateway.chat_review_allowed = False

        response = handle_api_request(
            self.service,
            "POST",
            f"/api/formulas/formula_euler_identity/deep-dive/sessions/{created['id']}/chat",
            {"message": "Continue with the formula."},
        )

        self.assertEqual(response.status, 200)
        self.assertTrue(response.payload["withdrawn"])
        self.assertIn("withdrawn", response.payload["reply"])
        self.assertNotIn("$x=1$", response.payload["reply"])
        self.assertEqual(len(self.gateway.review_calls), 1)
        self.assertEqual(
            self.gateway.review_calls[0][3],
            "The key idea is $x=1$.",
        )
        persisted = self.sessions.get("formula_euler_identity", created["id"])
        self.assertEqual(persisted["messages"][-1]["role"], "assistant")
        self.assertIn("withdrawn", persisted["messages"][-1]["content"])

    def test_assessment_request_is_refused_without_solving(self):
        created = handle_api_request(
            self.service,
            "POST",
            "/api/formulas/formula_euler_identity/deep-dive/sessions",
            {},
        ).payload

        response = handle_api_request(
            self.service,
            "POST",
            f"/api/formulas/formula_euler_identity/deep-dive/sessions/{created['id']}/chat",
            {"message": "Please solve this homework problem for me."},
        )

        self.assertEqual(response.status, 200)
        self.assertIn("cannot help solve", response.payload["reply"])
        self.assertEqual(self.gateway.chat_calls, [])
        self.assertEqual(self.gateway.review_calls, [])

    def test_initial_article_is_unchanged_after_long_conversation(self):
        created = handle_api_request(
            self.service,
            "POST",
            "/api/formulas/formula_euler_identity/deep-dive/sessions",
            {},
        ).payload
        original_article = created["article"]

        for number in range(8):
            handle_api_request(
                self.service,
                "POST",
                f"/api/formulas/formula_euler_identity/deep-dive/sessions/{created['id']}/chat",
                {"message": f"Tell me more, point {number}."},
            )

        persisted = self.sessions.get("formula_euler_identity", created["id"])
        self.assertEqual(persisted["article"], original_article)

    def test_chat_keeps_user_message_when_reply_fails(self):
        created = handle_api_request(
            self.service,
            "POST",
            "/api/formulas/formula_euler_identity/deep-dive/sessions",
            {},
        ).payload

        def fail_reply(formula, deep_dive, messages):
            raise SynthesisError("provider did not return a reply")

        self.gateway.chat = fail_reply
        response = handle_api_request(
            self.service,
            "POST",
            f"/api/formulas/formula_euler_identity/deep-dive/sessions/{created['id']}/chat",
            {"message": "Please preserve this question."},
        )

        self.assertEqual(response.status, 502)
        self.assertEqual(response.payload["error"]["code"], "upstream_error")
        persisted = self.sessions.get("formula_euler_identity", created["id"])
        self.assertEqual(
            [(item["role"], item["content"]) for item in persisted["messages"]],
            [("user", "Please preserve this question.")],
        )

    def test_sessions_can_be_deleted_from_local_storage(self):
        created = handle_api_request(
            self.service,
            "POST",
            "/api/formulas/formula_euler_identity/deep-dive/sessions",
            {},
        ).payload
        response = handle_api_request(
            self.service,
            "DELETE",
            f"/api/formulas/formula_euler_identity/deep-dive/sessions/{created['id']}",
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(self.sessions.list("formula_euler_identity"), [])
        with self.assertRaises(NotFoundError):
            self.sessions.get("formula_euler_identity", created["id"])

    def test_relationship_sessions_explain_the_saved_relation_and_continue_in_chat(self):
        created = handle_api_request(
            self.service,
            "POST",
            "/api/edges/edge_complex_to_euler/deep-dive/sessions",
            {},
        )
        self.assertEqual(created.status, 201)
        self.assertIn("relationship links", created.payload["article"]["introduction"])
        relationship = self.gateway.relationship_calls[0][0]
        self.assertEqual(relationship["relation"], "prerequisite")
        self.assertEqual(relationship["source_formula"]["id"], "formula_complex_exponential")

        chat = handle_api_request(
            self.service,
            "POST",
            f"/api/edges/edge_complex_to_euler/deep-dive/sessions/{created.payload['id']}/chat",
            {"message": "Why are these equivalent views?"},
        )
        self.assertEqual(chat.status, 200)
        self.assertEqual(len(chat.payload["session"]["messages"]), 2)
        self.assertEqual(self.gateway.chat_calls[-1][0]["id"], "edge_complex_to_euler")

    def test_unconfirmed_manual_relationship_shows_only_the_saved_note(self):
        self.gateway.relationship_sources = []
        self.gateway.relationship_validation_sources = []
        self.gateway.relationship_explanation_reasonable = False
        self.gateway.relationship_web_supported = False
        edge = self.service.add_edge(
            source_ref="formula_taylor_series",
            target_ref="formula_complex_exponential",
            relation="derivation_basis",
            rationale="Synthetic manual rationale for this test relationship.",
            source_ids=[],
            manual=True,
        )
        created = handle_api_request(
            self.service,
            "POST",
            f"/api/edges/{edge['id']}/deep-dive/sessions",
            {},
        )
        self.assertEqual(created.status, 201)
        self.assertEqual(edge["evidence_status"], "unverified")
        self.assertEqual(
            created.payload["article"]["introduction"],
            "Synthetic manual rationale for this test relationship.",
        )
        self.assertEqual(created.payload["sources"], [])
        self.assertEqual(created.payload["warnings"], [])
        self.assertEqual(self.gateway.relationship_calls, [])

    def test_unconfirmed_manual_relationship_without_note_says_relationship_unclear(self):
        self.gateway.relationship_explanation_reasonable = False
        self.gateway.relationship_web_supported = False
        edge = self.service.add_edge(
            source_ref="formula_taylor_series",
            target_ref="formula_complex_exponential",
            relation="derivation_basis",
            rationale="",
            source_ids=[],
            manual=True,
        )
        created = handle_api_request(
            self.service,
            "POST",
            f"/api/edges/{edge['id']}/deep-dive/sessions",
            {},
        )

        self.assertEqual(created.status, 201)
        self.assertEqual(
            created.payload["article"]["introduction"],
            "Relationship unclear.",
        )
        self.assertEqual(created.payload["warnings"], [])
        self.assertEqual(self.gateway.relationship_calls, [])

    def test_unconfirmed_manual_relationship_chat_does_not_call_ai(self):
        self.gateway.relationship_explanation_reasonable = False
        self.gateway.relationship_web_supported = False
        edge = self.service.add_edge(
            source_ref="formula_taylor_series",
            target_ref="formula_complex_exponential",
            relation="derivation_basis",
            rationale="My unconfirmed note.",
            source_ids=[],
            manual=True,
        )
        created = handle_api_request(
            self.service,
            "POST",
            f"/api/edges/{edge['id']}/deep-dive/sessions",
            {},
        ).payload
        response = handle_api_request(
            self.service,
            "POST",
            f"/api/edges/{edge['id']}/deep-dive/sessions/{created['id']}/chat",
            {"message": "Please explain more."},
        )

        self.assertEqual(response.status, 400)
        self.assertEqual(self.gateway.chat_calls, [])

    def test_confirmed_manual_relationship_generates_ai_content_with_user_note(self):
        self.gateway.relationship_explanation_reasonable = True
        self.gateway.relationship_web_supported = True
        edge = self.service.add_edge(
            source_ref="formula_taylor_series",
            target_ref="formula_complex_exponential",
            relation="derivation_basis",
            rationale="Synthetic manual rationale for this test relationship.",
            source_ids=[],
            manual=True,
        )
        created = handle_api_request(
            self.service,
            "POST",
            f"/api/edges/{edge['id']}/deep-dive/sessions",
            {},
        )

        self.assertEqual(edge["evidence_status"], "supported")
        self.assertEqual(created.status, 201)
        self.assertIn("relationship links", created.payload["article"]["introduction"])
        self.assertEqual(len(self.gateway.relationship_calls), 1)
        self.assertEqual(
            self.gateway.relationship_calls[0][0]["rationale"],
            "Synthetic manual rationale for this test relationship.",
        )

    def test_ai_relationship_without_sources_still_generates_ai_content(self):
        edge = self.repository.add_edge(
            edge_id="edge_ai_unverified",
            source_id="formula_taylor_series",
            target_id="formula_complex_exponential",
            relation="derivation_basis",
            rationale="AI identified a shared series structure.",
            sources=[],
        )
        self.assertEqual(edge.created_by, "ai")
        self.assertEqual(edge.evidence_status.value, "unverified")

        created = handle_api_request(
            self.service,
            "POST",
            "/api/edges/edge_ai_unverified/deep-dive/sessions",
            {},
        )

        self.assertEqual(created.status, 201)
        self.assertIn("relationship links", created.payload["article"]["introduction"])
        self.assertEqual(len(self.gateway.relationship_calls), 1)

    def test_reasonable_but_uncited_manual_relationship_is_unverified(self):
        self.gateway.relationship_validation_sources = []
        self.gateway.relationship_explanation_reasonable = True
        self.gateway.relationship_web_supported = False
        edge = self.service.add_edge(
            source_ref="formula_taylor_series",
            target_ref="formula_complex_exponential",
            relation="derivation_basis",
            rationale="The model thinks this connection is reasonable.",
            source_ids=[],
            manual=True,
        )
        self.assertEqual(edge["evidence_status"], "unverified")
        self.assertFalse(edge["confirmed_by_evidence"])

    def test_unexplained_manual_relationship_without_support_is_unverified(self):
        self.gateway.relationship_sources = []
        self.gateway.relationship_validation_sources = []
        self.gateway.relationship_explanation_reasonable = False
        self.gateway.relationship_web_supported = False
        edge = self.service.add_edge(
            source_ref="formula_taylor_series",
            target_ref="formula_complex_exponential",
            relation="derivation_basis",
            rationale="",
            source_ids=[],
            manual=True,
        )
        self.assertEqual(edge["evidence_status"], "unverified")
        self.assertFalse(edge["confirmed_by_evidence"])

    def test_manual_relationship_with_web_support_is_verified(self):
        self.gateway.relationship_explanation_reasonable = False
        self.gateway.relationship_web_supported = True
        edge = self.service.add_edge(
            source_ref="formula_taylor_series",
            target_ref="formula_complex_exponential",
            relation="derivation_basis",
            rationale="",
            source_ids=[],
            manual=True,
        )
        self.assertEqual(edge["evidence_status"], "supported")
        self.assertTrue(edge["confirmed_by_evidence"])
        self.assertEqual(len(edge["sources"]), 1)

    def test_edge_payload_preserves_manual_relationship_origin(self):
        edge = self.service.add_edge(
            source_ref="formula_taylor_series",
            target_ref="formula_complex_exponential",
            relation="derivation_basis",
            rationale="A manually selected relationship.",
            source_ids=[],
            manual=True,
        )
        self.assertEqual(edge["created_by"], "manual")

    def test_deleting_formula_removes_deep_dives_and_introduction(self):
        node_id = "formula_euler_identity"
        self.introductions.save(node_id, "Saved introduction text.")
        session_payload = {
            "title": "Saved dive",
            "article": {"introduction": "A saved dive.", "sections": []},
            "sources": [],
            "warnings": [],
        }
        self.sessions.create(node_id, session_payload)
        edge = self.repository.add_edge(
            edge_id="edge_cascade",
            source_id=node_id,
            target_id="formula_complex_exponential",
            relation="generalization",
            rationale="Cascade test relationship.",
            sources=[],
        )
        self.repository.save()
        self.sessions.create("relationship:edge_cascade", session_payload)

        result = self.service.delete_formula(node_id)

        self.assertEqual(result["deleted_deep_dive_sessions"], 2)
        self.assertTrue(result["deleted_introduction"])
        self.assertEqual(self.sessions.list(node_id), [])
        self.assertEqual(self.sessions.list("relationship:edge_cascade"), [])
        self.assertIsNone(self.introductions.get(node_id))
        self.assertNotIn(
            edge.id,
            [item.id for item in self.repository.document.edges],
        )

    def test_deleting_edge_removes_its_relationship_sessions(self):
        edge = self.repository.add_edge(
            edge_id="edge_delete",
            source_id="formula_taylor_series",
            target_id="formula_complex_exponential",
            relation="derivation_basis",
            rationale="Delete test relationship.",
            sources=[],
        )
        self.repository.save()
        self.sessions.create(
            "relationship:edge_delete",
            {
                "title": "Relationship dive",
                "article": {"introduction": "A saved relationship dive.", "sections": []},
                "sources": [],
                "warnings": [],
            },
        )

        result = self.service.delete_edge(edge.id)

        self.assertEqual(result["deleted_deep_dive_sessions"], 1)
        self.assertEqual(self.sessions.list("relationship:edge_delete"), [])

    def test_openapi_exposes_deep_dive_session_routes(self):
        paths = openapi_document()["paths"]
        self.assertIn("/api/formulas/{formula_id}/deep-dive/sessions", paths)
        self.assertIn("/api/formulas/{formula_id}/deep-dive/sessions/{session_id}", paths)
        self.assertIn(
            "/api/formulas/{formula_id}/deep-dive/sessions/{session_id}/chat",
            paths,
        )
        self.assertIn("/api/edges/{edge_id}/deep-dive/sessions", paths)


if __name__ == "__main__":
    unittest.main()
