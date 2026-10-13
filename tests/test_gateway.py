import json
import tempfile
import unittest
from pathlib import Path

from mathernet.api import handle_api_request
from mathernet.gateway import GatewayConfig, GatewayStore
from mathernet.repository import GraphRepository
from mathernet.services import MathernetService


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = GatewayStore(Path(self.temporary.name) / "gateway.json")
        self.service = MathernetService(
            GraphRepository(Path(self.temporary.name) / "graph.json"),
            gateway_store=self.store,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_config_is_masked_and_persisted_locally(self):
        response = handle_api_request(
            self.service,
            "PATCH",
            "/api/gateway",
            {
                "provider": "openai",
                "api_key": "sk-1234567890",
                "model": "gpt-5-mini",
                "search_engine": "google",
                "search_api_key": "search-secret",
                "search_engine_id": "engine-id",
            },
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.payload["provider"], "openai")
        self.assertNotIn("sk-1234567890", json.dumps(response.payload))
        self.assertNotIn("search-secret", json.dumps(response.payload))
        self.assertTrue(response.payload["api_key_hint"].startswith("sk-"))

        stored = json.loads((Path(self.temporary.name) / "gateway.json").read_text())
        self.assertEqual(stored["api_key"], "sk-1234567890")

    def test_blank_secret_keeps_existing_key(self):
        self.store.save(
            GatewayConfig(
                provider="anthropic",
                api_key="secret-value",
                model="claude-3-5-sonnet-latest",
                search_engine="baidu",
            )
        )
        response = handle_api_request(
            self.service,
            "PATCH",
            "/api/gateway",
            {"provider": "anthropic", "api_key": "", "model": "claude-3-5-sonnet-latest", "search_engine": "baidu"},
        )
        self.assertEqual(response.payload["api_key_hint"], "sec…ue")
        self.assertEqual(self.store.load().api_key, "secret-value")

    def test_openapi_exposes_gateway_routes(self):
        response = handle_api_request(self.service, "GET", "/api/openapi.json")
        self.assertIn("/api/gateway", response.payload["paths"])
        self.assertIn("/api/gateway/mcp", response.payload["paths"])

    def test_mcp_route_accepts_command_http_url_and_headers_json(self):
        response = handle_api_request(
            self.service,
            "PATCH",
            "/api/gateway/mcp",
            {
                "transport": "http",
                "command": "",
                "http_url": "https://search.example/mcp",
                "tool_name": "web_search",
                "headers_json": '{"Authorization":"Bearer local-token"}',
            },
        )
        self.assertEqual(response.status, 200)
        config = self.store.load()
        self.assertEqual(config.mcp_transport, "http")
        self.assertEqual(config.mcp_http_url, "https://search.example/mcp")
        self.assertEqual(config.mcp_tool_name, "web_search")
        self.assertEqual(config.mcp_headers, '{"Authorization":"Bearer local-token"}')
        self.assertNotIn("local-token", json.dumps(response.payload))


if __name__ == "__main__":
    unittest.main()
