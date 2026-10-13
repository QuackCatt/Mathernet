import json
import tempfile
import unittest
from pathlib import Path

from mathernet.api import handle_api_request
from mathernet.gateway import GatewayConfig, GatewayStore
from mathernet.providers import (
    AnthropicMessagesAdapter,
    OpenAIChatAdapter,
    OpenAIResponsesAdapter,
    ProviderRequest,
    adapter_for_config,
    resolve_provider_config,
)
from mathernet.repository import GraphRepository
from mathernet.services import MathernetService


class RecordingTransport:
    def __init__(self):
        self.calls = []

    def post(self, endpoint, headers, payload, timeout):
        self.calls.append({
            "endpoint": endpoint,
            "headers": headers,
            "payload": payload,
            "timeout": timeout,
        })
        return {
            "id": "response-1",
            "model": payload["model"],
            "choices": [{"message": {"content": "connected"}}],
        }


class ProviderAdapterTests(unittest.TestCase):
    def test_openai_chat_adapter_serves_all_compatible_presets(self):
        for provider in ("deepseek", "qwen", "openrouter"):
            with self.subTest(provider=provider):
                transport = RecordingTransport()
                config = resolve_provider_config(
                    provider=provider,
                    api_key="secret",
                    model=f"{provider}-model",
                )
                adapter = adapter_for_config(config, transport=transport)
                self.assertIsInstance(adapter, OpenAIChatAdapter)

                response = adapter.complete(
                    ProviderRequest(
                        model=config.model,
                        api_key=config.api_key,
                        system_prompt="system",
                        user_prompt="user",
                    )
                )

                call = transport.calls[0]
                self.assertEqual(response.text, "connected")
                self.assertEqual(call["headers"]["Authorization"], "Bearer secret")
                self.assertEqual(call["headers"]["User-Agent"], "Mathernet/1.0")
                self.assertEqual(call["payload"]["messages"][0]["role"], "system")
                self.assertEqual(call["payload"]["messages"][1]["content"], "user")
                self.assertIn("/chat/completions", call["endpoint"])

    def test_anthropic_adapter_uses_messages_protocol_and_x_api_key(self):
        transport = RecordingTransport()
        config = resolve_provider_config(
            provider="anthropic",
            api_key="anthropic-secret",
            model="claude-model",
        )
        adapter = adapter_for_config(config, transport=transport)
        self.assertIsInstance(adapter, AnthropicMessagesAdapter)

        adapter.complete(
            ProviderRequest(
                model=config.model,
                api_key=config.api_key,
                system_prompt="system",
                user_prompt="user",
                json_schema={"type": "object"},
            )
        )

        call = transport.calls[0]
        self.assertEqual(call["headers"]["x-api-key"], "anthropic-secret")
        self.assertNotIn("Authorization", call["headers"])
        self.assertEqual(call["payload"]["system"], "system")
        self.assertEqual(call["payload"]["tool_choice"]["name"], "save_formula_card")

    def test_openai_responses_adapter_builds_structured_output(self):
        transport = RecordingTransport()
        config = resolve_provider_config(
            provider="openai",
            api_key="openai-secret",
            model="gpt-model",
        )
        adapter = adapter_for_config(config, transport=transport)
        self.assertIsInstance(adapter, OpenAIResponsesAdapter)

        adapter.complete(
            ProviderRequest(
                model=config.model,
                api_key=config.api_key,
                system_prompt="system",
                user_prompt="user",
                json_schema={"type": "object", "properties": {}},
            )
        )

        call = transport.calls[0]
        self.assertEqual(call["payload"]["instructions"], "system")
        self.assertEqual(
            call["payload"]["text"]["format"]["type"],
            "json_schema",
        )

    def test_new_compatible_provider_needs_configuration_not_gateway_code(self):
        transport = RecordingTransport()
        config = resolve_provider_config(
            provider="future-provider",
            api_key="secret",
            model="future-model",
            api_format="openai_chat",
            base_url="https://ai.example.com",
            endpoint_path="/api/chat/completions",
            auth_style="bearer",
        )
        adapter = adapter_for_config(config, transport=transport)
        self.assertIsInstance(adapter, OpenAIChatAdapter)
        adapter.complete(
            ProviderRequest(
                model=config.model,
                api_key=config.api_key,
                system_prompt="system",
            )
        )
        self.assertEqual(
            transport.calls[0]["endpoint"],
            "https://ai.example.com/api/chat/completions",
        )


class ProviderConfigCompatibilityTests(unittest.TestCase):
    def test_legacy_gateway_config_is_mapped_to_a_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gateway.json"
            path.write_text(json.dumps({
                "provider": "deepseek",
                "api_key": "secret",
                "model": "deepseek-chat",
            }))
            config = GatewayStore(path).load()

        self.assertEqual(config.api_format, "openai_chat")
        self.assertEqual(config.auth_style, "bearer")
        self.assertEqual(config.endpoint_path, "/v1/chat/completions")
        self.assertTrue(config.ai_configured)

    def test_openrouter_preset_uses_its_api_prefix(self):
        config = resolve_provider_config(
            provider="openrouter",
            api_key="secret",
            model="openai/gpt-4o-mini",
        )
        self.assertEqual(
            config.endpoint,
            "https://openrouter.ai/api/v1/chat/completions",
        )

    def test_switching_provider_replaces_protocol_preset(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GatewayStore(Path(directory) / "gateway.json")
            store.save(GatewayConfig(
                provider="deepseek",
                api_key="deepseek-key",
                model="deepseek-chat",
            ))
            service = MathernetService(
                GraphRepository(Path(directory) / "graph.json"),
                gateway_store=store,
            )
            response = handle_api_request(
                service,
                "PATCH",
                "/api/gateway",
                {
                    "provider": "openai",
                    "api_key": "openai-key",
                    "model": "gpt-5-mini",
                },
            )

            self.assertEqual(response.status, 200)
            config = store.load()
            self.assertEqual(config.provider, "openai")
            self.assertEqual(config.api_format, "openai_responses")
            self.assertEqual(config.endpoint_path, "/v1/responses")


if __name__ == "__main__":
    unittest.main()
