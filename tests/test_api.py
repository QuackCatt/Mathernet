import tempfile
import unittest
from pathlib import Path

from mathernet.api import (
    DEFAULT_WEB_ROOT,
    handle_api_request,
    openapi_document,
    resolve_web_asset,
)
from mathernet.errors import NotFoundError
from mathernet.repository import GraphRepository
from mathernet.services import MathernetService
from tests.test_data import synthetic_graph_payload


ROOT = Path(__file__).resolve().parents[1]


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = GraphRepository(Path(self.temporary.name) / "graph.json")
        self.repository.document = self.repository.document.from_dict(synthetic_graph_payload())
        self.repository.save()
        self.service = MathernetService(self.repository)

    def tearDown(self):
        self.temporary.cleanup()

    def test_health_card_and_openapi_contract(self):
        health = handle_api_request(self.service, "GET", "/api/health")
        self.assertEqual(health.status, 200)
        self.assertEqual(health.payload["formula_count"], 3)

        formulas = handle_api_request(self.service, "GET", "/api/formulas")
        self.assertEqual(
            formulas.payload["status_counts"],
            {"all": 3, "learning": 1, "reviewed": 1},
        )

        card = handle_api_request(
            self.service,
            "GET",
            "/api/formulas/formula_euler_identity",
        )
        self.assertEqual(card.status, 200)
        self.assertEqual(card.payload["formula"]["name"], "Concept Gamma")
        self.assertIn("/api/edges/{edge_id}/confirm", openapi_document()["paths"])

    def test_learn_reuses_an_existing_formula_with_a_success_status(self):
        class Agent:
            def __init__(self, service):
                self.service = service

            def learn(self, query):
                from mathernet.agent import LearnResult

                node = self.service.repository.find_formula(query)
                return LearnResult(node=node, created=False)

        self.service.agent = Agent(self.service)
        response = handle_api_request(
            self.service,
            "POST",
            "/api/learn",
            {"query": "Concept Gamma"},
        )
        self.assertEqual(response.status, 200)
        self.assertFalse(response.payload["created"])

    def test_formula_candidates_are_read_only_and_reuse_local_matches(self):
        class Agent:
            def discover_formula_candidates(self, query):
                from mathernet.agent_skills import FormulaCandidate

                return [
                    FormulaCandidate(
                        canonical_name="Concept Gamma",
                        latex="c=d",
                        summary="Synthetic local match.",
                        topic="test-topic",
                        reason="Exact local match.",
                        confidence=0.98,
                        local_formula_id="formula_euler_identity",
                    ),
                    FormulaCandidate(
                        canonical_name="Concept Delta",
                        latex="d=e",
                        summary="Synthetic nearby candidate.",
                        topic="test-topic",
                        reason="A plausible nearby formula.",
                        confidence=0.81,
                    ),
                ]

            def learn(self, query):
                raise AssertionError("candidate search must not learn")

        self.service.agent = Agent()
        before = self.service.revision
        response = handle_api_request(
            self.service,
            "POST",
            "/api/learn/candidates",
            {"query": "a synthetic relation near Concept Gamma"},
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(len(response.payload["candidates"]), 2)
        self.assertTrue(response.payload["candidates"][0]["existing"])
        self.assertEqual(
            response.payload["candidates"][0]["local_formula_id"],
            "formula_euler_identity",
        )
        self.assertFalse(response.payload["candidates"][1]["existing"])
        self.assertEqual(self.service.revision, before)
        self.assertIn(
            "/api/learn/candidates",
            openapi_document()["paths"],
        )

    def test_edge_requires_confirmation_then_accepts(self):
        created = handle_api_request(
            self.service,
            "POST",
            "/api/edges",
            {
                "source_id": "formula_taylor_series",
                "target_id": "formula_complex_exponential",
                "relation": "prerequisite",
                "rationale": "Synthetic prerequisite rationale.",
                "source_ids": ["src_alpha", "src_beta"],
            },
        )
        self.assertEqual(created.status, 201)
        self.assertTrue(created.payload["requires_user_confirmation"])

        confirmed = handle_api_request(
            self.service,
            "POST",
            f"/api/edges/{created.payload['id']}/confirm",
            {},
        )
        self.assertEqual(confirmed.status, 200)
        self.assertTrue(confirmed.payload["accepted"])

    def test_manual_edge_can_be_created_without_sources_and_deleted(self):
        created = handle_api_request(
            self.service,
            "POST",
            "/api/edges",
            {
                "source_id": "formula_taylor_series",
                "target_id": "formula_complex_exponential",
                "relation": "equivalent_form",
                "rationale": "",
                "source_ids": [],
                "manual": True,
            },
        )
        self.assertEqual(created.status, 201)
        self.assertTrue(created.payload["accepted"])
        self.assertEqual(created.payload["evidence_status"], "unverified")
        deleted = handle_api_request(
            self.service,
            "DELETE",
            f"/api/edges/{created.payload['id']}",
            {"expected_updated_at": created.payload["updated_at"]},
        )
        self.assertEqual(deleted.status, 200)
        self.assertTrue(deleted.payload["deleted"])
        self.assertIn("delete", openapi_document()["paths"]["/api/edges/{edge_id}"])

    def test_unknown_fields_and_routes_use_stable_errors(self):
        invalid = handle_api_request(
            self.service,
            "PATCH",
            "/api/formulas/formula_euler_identity/status",
            {"status": "learning", "unexpected": True},
        )
        self.assertEqual(invalid.status, 400)
        self.assertEqual(invalid.payload["error"]["code"], "validation_error")

        missing = handle_api_request(self.service, "GET", "/api/not-here")
        self.assertEqual(missing.status, 404)
        self.assertEqual(missing.payload["error"]["code"], "not_found")

    def test_options_is_ready_for_browser_clients(self):
        response = handle_api_request(self.service, "OPTIONS", "/api/formulas")
        self.assertEqual(response.status, 204)

    def test_static_web_assets_resolve_only_inside_the_web_root(self):
        web_root = DEFAULT_WEB_ROOT
        self.assertEqual(resolve_web_asset(web_root, "/"), web_root / "index.html")
        self.assertEqual(resolve_web_asset(web_root, "/app.js"), web_root / "app.js")
        with self.assertRaises(NotFoundError):
            resolve_web_asset(web_root, "/../README.md")
        with self.assertRaises(NotFoundError):
            resolve_web_asset(web_root, "/missing.js")


if __name__ == "__main__":
    unittest.main()
