import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mathernet.api import handle_api_request
from mathernet.errors import SynthesisError
from mathernet.gateway import GatewayConfig, GatewayStore, ProviderGateway
from mathernet.providers import ProviderResponse
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
                "provider": "deepseek",
                "api_key": "sk-1234567890",
                "search_engine": "google",
                "search_api_key": "search-secret",
                "search_engine_id": "engine-id",
            },
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(response.payload["provider"], "deepseek")
        self.assertNotIn("sk-1234567890", json.dumps(response.payload))
        self.assertNotIn("search-secret", json.dumps(response.payload))
        self.assertTrue(response.payload["api_key_hint"].startswith("sk-"))

        stored = json.loads((Path(self.temporary.name) / "gateway.json").read_text())
        self.assertEqual(stored["api_key"], "sk-1234567890")

    def test_blank_secret_keeps_existing_key(self):
        self.store.save(
            GatewayConfig(
                provider="deepseek",
                api_key="secret-value",
                search_engine="baidu",
            )
        )
        response = handle_api_request(
            self.service,
            "PATCH",
            "/api/gateway",
            {"provider": "deepseek", "api_key": "", "search_engine": "baidu"},
        )
        self.assertEqual(response.payload["api_key_hint"], "sec…ue")
        self.assertEqual(self.store.load().api_key, "secret-value")

    def test_failed_connection_test_persists_check_settings(self):
        response = handle_api_request(
            self.service,
            "PATCH",
            "/api/gateway",
            {"provider": "openrouter", "api_key": "bad-key", "model": "openai/gpt-4o-mini"},
        )
        self.assertEqual(response.payload["ai_connection_status"], "unknown")

        with patch(
            "mathernet.services.ProviderGateway.test_connection",
            side_effect=SynthesisError("AI provider request failed: invalid API key"),
        ):
            failed = handle_api_request(self.service, "POST", "/api/gateway/test-ai")

        self.assertEqual(failed.status, 502)
        self.assertEqual(self.store.load().ai_connection_status, "check_settings")
        reread = handle_api_request(self.service, "GET", "/api/gateway")
        self.assertEqual(reread.payload["ai_connection_status"], "check_settings")
        self.assertEqual(reread.payload["ai_configured"], True)

    def test_successful_connection_test_persists_connected(self):
        handle_api_request(
            self.service,
            "PATCH",
            "/api/gateway",
            {"provider": "deepseek", "api_key": "good-key"},
        )
        with patch(
            "mathernet.services.ProviderGateway.test_connection",
            return_value={"ok": True, "message": "connected"},
        ):
            response = handle_api_request(self.service, "POST", "/api/gateway/test-ai")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.payload["ai_connection_status"], "connected")
        self.assertEqual(self.store.load().ai_connection_status, "connected")

    def test_openapi_exposes_gateway_routes(self):
        response = handle_api_request(self.service, "GET", "/api/openapi.json")
        self.assertIn("/api/gateway", response.payload["paths"])
        self.assertIn("/api/gateway/models", response.payload["paths"])
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

    def test_structured_provider_requests_include_the_required_schema(self):
        captured_request = {}

        class FakeAdapter:
            def complete(self, request):
                captured_request["request"] = request
                return ProviderResponse(
                    text=json.dumps({
                        "title": "Context",
                        "introduction": "A useful exploration.",
                        "sections": [],
                        "sources": [],
                        "warnings": [],
                    }),
                    raw={},
                )

        gateway = ProviderGateway(
            GatewayConfig(provider="deepseek", api_key="test-key")
        )
        with patch("mathernet.gateway.adapter_for_config", return_value=FakeAdapter()):
            gateway.deep_dive({"name": "Test formula"}, [])

        request = captured_request["request"]
        self.assertIn("Required JSON schema:", request.system_prompt)
        self.assertIn('"introduction"', request.system_prompt)
        self.assertIn('"sections"', request.system_prompt)
        self.assertIn("Omit a topic instead of padding the article", request.system_prompt)

    def test_formula_introduction_requests_include_the_local_skill(self):
        captured_request = {}

        class FakeAdapter:
            def complete(self, request):
                captured_request["request"] = request
                introduction = " ".join(f"term{number}" for number in range(1, 121))
                return ProviderResponse(
                    text=json.dumps({"introduction": introduction}),
                    raw={},
                )

        gateway = ProviderGateway(
            GatewayConfig(provider="openrouter", api_key="test-key", model="openai/gpt-4o-mini")
        )
        with patch("mathernet.gateway.adapter_for_config", return_value=FakeAdapter()):
            introduction = gateway.introduce({"name": "Test formula"}, [])

        request = captured_request["request"]
        self.assertEqual(len(introduction.split()), 120)
        self.assertIn("formula introduction skill", request.system_prompt)
        self.assertIn("110-150 words", request.system_prompt)
        self.assertIn("Required JSON schema:", request.system_prompt)

    def test_relationship_validation_uses_web_research_schema(self):
        captured_request = {}

        class FakeAdapter:
            def complete(self, request):
                captured_request["request"] = request
                return ProviderResponse(
                    text=json.dumps({
                        "explanation_is_reasonable": False,
                        "web_supported": True,
                        "assessment": "Independent references support this relationship.",
                        "sources": [{
                            "title": "Relationship reference",
                            "url": "https://example.edu/relationship",
                            "publisher": "Example University",
                            "excerpt": "A reference supporting the connection.",
                        }],
                    }),
                    raw={},
                )

        gateway = ProviderGateway(
            GatewayConfig(provider="openrouter", api_key="test-key", model="openai/gpt-4o-mini")
        )
        with patch("mathernet.gateway.adapter_for_config", return_value=FakeAdapter()):
            validation = gateway.validate_relationship(
                {
                    "source_formula": {"id": "formula_a", "name": "A"},
                    "target_formula": {"id": "formula_b", "name": "B"},
                    "relation": "prerequisite",
                    "rationale": "",
                    "created_by": "manual",
                },
                [],
            )

        request = captured_request["request"]
        self.assertFalse(validation["explanation_is_reasonable"])
        self.assertTrue(validation["web_supported"])
        self.assertEqual(validation["sources"][0]["url"], "https://example.edu/relationship")
        self.assertIn("built-in web search when available", request.system_prompt)
        self.assertIn('"explanation_is_reasonable"', request.system_prompt)
        self.assertIn("Required JSON schema:", request.system_prompt)


if __name__ == "__main__":
    unittest.main()
