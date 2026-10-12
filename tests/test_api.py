import json
import tempfile
import unittest
from pathlib import Path

from mathernet.api import handle_api_request, openapi_document, resolve_web_asset
from mathernet.errors import NotFoundError
from mathernet.models import GraphDocument
from mathernet.repository import GraphRepository
from mathernet.services import MathernetService


ROOT = Path(__file__).resolve().parents[1]


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        payload = json.loads(
            (ROOT / "examples" / "demo_graph.json").read_text(encoding="utf-8")
        )
        self.repository = GraphRepository(Path(self.temporary.name) / "graph.json")
        self.repository.document = GraphDocument.from_dict(payload)
        self.repository.save()
        self.service = MathernetService(self.repository)

    def tearDown(self):
        self.temporary.cleanup()

    def test_health_card_and_openapi_contract(self):
        health = handle_api_request(self.service, "GET", "/api/health")
        self.assertEqual(health.status, 200)
        self.assertEqual(health.payload["formula_count"], 3)

        card = handle_api_request(
            self.service,
            "GET",
            "/api/formulas/formula_euler_identity",
        )
        self.assertEqual(card.status, 200)
        self.assertEqual(card.payload["formula"]["name"], "Euler's identity")
        self.assertIn("/api/edges/{edge_id}/confirm", openapi_document()["paths"])

    def test_edge_requires_confirmation_then_accepts(self):
        created = handle_api_request(
            self.service,
            "POST",
            "/api/edges",
            {
                "source_id": "formula_taylor_series",
                "target_id": "formula_complex_exponential",
                "relation": "prerequisite",
                "rationale": "Series foundations support the complex exponential.",
                "source_ids": ["src_taylor_series", "src_complex_exponential"],
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
        web_root = ROOT / "web"
        self.assertEqual(resolve_web_asset(web_root, "/"), web_root / "index.html")
        self.assertEqual(resolve_web_asset(web_root, "/app.js"), web_root / "app.js")
        with self.assertRaises(NotFoundError):
            resolve_web_asset(web_root, "/../README.md")
        with self.assertRaises(NotFoundError):
            resolve_web_asset(web_root, "/missing.js")


if __name__ == "__main__":
    unittest.main()
