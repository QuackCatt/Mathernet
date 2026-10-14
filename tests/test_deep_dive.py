import json
import tempfile
import unittest
from pathlib import Path

from mathernet.agent_skills import parse_formula_deep_dive
from mathernet.api import handle_api_request, openapi_document
from mathernet.deep_dive_sessions import DeepDiveSessionStore
from mathernet.errors import NotFoundError, SynthesisError
from mathernet.models import GraphDocument
from mathernet.repository import GraphRepository
from mathernet.services import MathernetService


ROOT = Path(__file__).resolve().parents[1]


class FakeDeepDiveGateway:
    def __init__(self):
        self.deep_dive_calls = []
        self.chat_calls = []

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


class DeepDiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        payload = json.loads(
            (ROOT / "examples" / "demo_graph.json").read_text(encoding="utf-8")
        )
        self.repository = GraphRepository(Path(self.temporary.name) / "graph.json")
        self.repository.document = GraphDocument.from_dict(payload)
        self.repository.save()
        self.gateway = FakeDeepDiveGateway()
        self.sessions = DeepDiveSessionStore(Path(self.temporary.name) / "sessions.json")
        self.service = MathernetService(
            self.repository,
            ai_gateway=self.gateway,
            deep_dive_sessions=self.sessions,
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

    def test_openapi_exposes_deep_dive_session_routes(self):
        paths = openapi_document()["paths"]
        self.assertIn("/api/formulas/{formula_id}/deep-dive/sessions", paths)
        self.assertIn("/api/formulas/{formula_id}/deep-dive/sessions/{session_id}", paths)
        self.assertIn(
            "/api/formulas/{formula_id}/deep-dive/sessions/{session_id}/chat",
            paths,
        )


if __name__ == "__main__":
    unittest.main()
