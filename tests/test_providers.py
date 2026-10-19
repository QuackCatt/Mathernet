import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mathernet.api import handle_api_request
from mathernet.errors import SynthesisError
from mathernet.gateway import GatewayConfig, GatewayStore
from mathernet.providers import (
    OpenAIChatAdapter,
    ProviderRequest,
    adapter_for_config,
    fetch_provider_models,
    provider_catalog,
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


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FlakyTransport(RecordingTransport):
    def __init__(self, failure_message="Upstream error from Nvidia: Service temporarily overloaded"):
        super().__init__()
        self.attempts = 0
        self.failure_message = failure_message

    def post(self, endpoint, headers, payload, timeout):
        self.attempts += 1
        if self.attempts == 1:
            raise SynthesisError(self.failure_message)
        return super().post(endpoint, headers, payload, timeout)


class ProviderAdapterTests(unittest.TestCase):
    def test_only_deepseek_and_openrouter_are_exposed(self):
        catalog = provider_catalog()
        self.assertEqual([item["id"] for item in catalog], ["deepseek", "openrouter"])
        by_id = {item["id"]: item for item in catalog}
        self.assertTrue(by_id["deepseek"]["managed_model"])
        self.assertFalse(by_id["deepseek"]["model_required"])
        self.assertFalse(by_id["openrouter"]["managed_model"])
        self.assertTrue(by_id["openrouter"]["model_required"])

    def test_deepseek_uses_managed_model_and_openai_chat_protocol(self):
        transport = RecordingTransport()
        config = resolve_provider_config(provider="deepseek", api_key="synthetic-token", model="")
        adapter = adapter_for_config(config, transport=transport)
        self.assertIsInstance(adapter, OpenAIChatAdapter)
        self.assertEqual(config.model, "deepseek-chat")

        response = adapter.complete(
            ProviderRequest(
                model=config.model,
                api_key=config.api_key,
                system_prompt="system",
                user_prompt="user",
                json_schema={"type": "object"},
            )
        )

        call = transport.calls[0]
        self.assertEqual(response.text, "connected")
        self.assertEqual(call["endpoint"], "https://api.deepseek.com/v1/chat/completions")
        self.assertEqual(call["headers"]["Authorization"], "Bearer synthetic-token")
        self.assertEqual(call["payload"]["model"], "deepseek-chat")
        self.assertEqual(call["payload"]["response_format"], {"type": "json_object"})

    def test_openrouter_requires_a_route_and_uses_router_headers(self):
        transport = RecordingTransport()
        config = resolve_provider_config(
            provider="openrouter",
            api_key="synthetic-router-token",
            model="openai/gpt-4o-mini",
        )
        adapter = adapter_for_config(config, transport=transport)
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
        self.assertEqual(call["endpoint"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(call["headers"]["Authorization"], "Bearer synthetic-router-token")
        self.assertEqual(call["headers"]["HTTP-Referer"], "http://127.0.0.1")
        self.assertEqual(call["headers"]["X-Title"], "Mathernet")
        self.assertEqual(call["payload"]["model"], "openai/gpt-4o-mini")
        self.assertNotIn("response_format", call["payload"])
        self.assertNotIn("reasoning", call["payload"])
        self.assertNotIn("max_tokens", call["payload"])

    def test_openrouter_model_is_required(self):
        with self.assertRaisesRegex(Exception, "model is required"):
            resolve_provider_config(provider="openrouter", api_key="synthetic-token", model="")

    def test_retries_transient_provider_overload(self):
        transport = FlakyTransport()
        config = resolve_provider_config(
            provider="openrouter",
            api_key="synthetic-token",
            model="nvidia/nemotron-3-ultra-550b-a55b:free",
        )
        adapter = adapter_for_config(
            config,
            transport=transport,
            retry_delay_seconds=0,
        )
        response = adapter.complete(
            ProviderRequest(
                model=config.model,
                api_key=config.api_key,
                system_prompt="system",
                user_prompt="user",
            )
        )

        self.assertEqual(response.text, "connected")
        self.assertEqual(transport.attempts, 2)

    def test_retries_incomplete_provider_reads(self):
        transport = FlakyTransport(
            "AI provider request failed: IncompleteRead(12 bytes read)"
        )
        config = resolve_provider_config(
            provider="openrouter",
            api_key="synthetic-token",
            model="openai/gpt-4o-mini",
        )
        adapter = adapter_for_config(config, transport=transport, retry_delay_seconds=0)
        response = adapter.complete(
            ProviderRequest(
                model=config.model,
                api_key=config.api_key,
                system_prompt="system",
                user_prompt="user",
            )
        )

        self.assertEqual(response.text, "connected")
        self.assertEqual(transport.attempts, 2)

    def test_fetches_openrouter_model_routes(self):
        with patch(
            "mathernet.providers.open_url",
            return_value=FakeResponse({
                "data": [
                    {"id": "z-ai/glm-5.2", "name": "GLM 5.2"},
                    {"id": "openai/gpt-4o-mini", "name": "GPT-4o mini"},
                ]
            }),
        ) as open_url:
            models = fetch_provider_models("openrouter", "synthetic-token")

        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "https://openrouter.ai/api/v1/models")
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-token")
        self.assertEqual(
            [model["id"] for model in models],
            ["openai/gpt-4o-mini", "z-ai/glm-5.2"],
        )


class ProviderConfigCompatibilityTests(unittest.TestCase):
    def test_legacy_gateway_config_is_mapped_to_deepseek_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gateway.json"
            path.write_text(json.dumps({
                "provider": "deepseek",
                "api_key": "synthetic-token",
                "model": "",
            }))
            config = GatewayStore(path).load()

        self.assertEqual(config.api_format, "openai_chat")
        self.assertEqual(config.auth_style, "bearer")
        self.assertEqual(config.model, "deepseek-chat")
        self.assertTrue(config.ai_configured)

    def test_switching_provider_replaces_the_provider_preset(self):
        with tempfile.TemporaryDirectory() as directory:
            store = GatewayStore(Path(directory) / "gateway.json")
            store.save(GatewayConfig(provider="deepseek", api_key="synthetic-deepseek-token"))
            service = MathernetService(
                GraphRepository(Path(directory) / "graph.json"),
                gateway_store=store,
            )
            response = handle_api_request(
                service,
                "PATCH",
                "/api/gateway",
                {
                    "provider": "openrouter",
                    "api_key": "synthetic-router-token",
                    "model": "openai/gpt-4o-mini",
                },
            )

            self.assertEqual(response.status, 200)
            config = store.load()
            self.assertEqual(config.provider, "openrouter")
            self.assertEqual(config.endpoint_path, "/api/v1/chat/completions")
            self.assertEqual(config.model, "openai/gpt-4o-mini")


if __name__ == "__main__":
    unittest.main()
