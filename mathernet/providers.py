from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import SynthesisError, ValidationError
from .http_client import open_url


API_FORMAT_ANTHROPIC_MESSAGES = "anthropic_messages"
API_FORMAT_OPENAI_CHAT = "openai_chat"
API_FORMAT_OPENAI_RESPONSES = "openai_responses"

AUTH_BEARER = "bearer"
AUTH_X_API_KEY = "x-api-key"

API_FORMATS = (
    API_FORMAT_ANTHROPIC_MESSAGES,
    API_FORMAT_OPENAI_CHAT,
    API_FORMAT_OPENAI_RESPONSES,
)
AUTH_STYLES = (AUTH_BEARER, AUTH_X_API_KEY)


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    label: str
    api_format: str
    base_url: str
    endpoint_path: str
    auth_style: str
    default_model: str


PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "anthropic": ProviderPreset(
        label="Anthropic",
        api_format=API_FORMAT_ANTHROPIC_MESSAGES,
        base_url="https://api.anthropic.com",
        endpoint_path="/v1/messages",
        auth_style=AUTH_X_API_KEY,
        default_model="claude-3-5-sonnet-latest",
    ),
    "openai": ProviderPreset(
        label="OpenAI",
        api_format=API_FORMAT_OPENAI_RESPONSES,
        base_url="https://api.openai.com",
        endpoint_path="/v1/responses",
        auth_style=AUTH_BEARER,
        default_model="gpt-5-mini",
    ),
    "deepseek": ProviderPreset(
        label="DeepSeek",
        api_format=API_FORMAT_OPENAI_CHAT,
        base_url="https://api.deepseek.com",
        endpoint_path="/v1/chat/completions",
        auth_style=AUTH_BEARER,
        default_model="deepseek-chat",
    ),
    "qwen": ProviderPreset(
        label="Qwen",
        api_format=API_FORMAT_OPENAI_CHAT,
        base_url="https://dashscope.aliyuncs.com/compatible-mode",
        endpoint_path="/v1/chat/completions",
        auth_style=AUTH_BEARER,
        default_model="qwen-plus",
    ),
    "openrouter": ProviderPreset(
        label="OpenRouter",
        api_format=API_FORMAT_OPENAI_CHAT,
        base_url="https://openrouter.ai",
        endpoint_path="/api/v1/chat/completions",
        auth_style=AUTH_BEARER,
        default_model="openai/gpt-4o-mini",
    ),
}


@dataclass(frozen=True, slots=True)
class ResolvedProviderConfig:
    provider: str
    api_key: str
    model: str
    api_format: str
    base_url: str
    endpoint_path: str
    auth_style: str

    @property
    def endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/{self.endpoint_path.lstrip('/')}"


@dataclass(slots=True)
class ProviderRequest:
    model: str
    api_key: str
    system_prompt: str
    user_prompt: str = ""
    json_schema: dict[str, Any] | None = None
    temperature: float = 0.1


@dataclass(slots=True)
class ProviderResponse:
    text: str
    raw: dict[str, Any]
    request_id: str = ""
    model: str = ""


class ProviderTransport(Protocol):
    def post(
        self,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]: ...


class UrllibProviderTransport:
    def post(
        self,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with open_url(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", "replace")
            try:
                detail = json.loads(body)
                error_detail = detail.get("error") if isinstance(detail, dict) else None
                message = (
                    error_detail.get("message")
                    if isinstance(error_detail, dict)
                    else detail.get("message")
                    if isinstance(detail, dict)
                    else ""
                )
            except (json.JSONDecodeError, AttributeError, OSError):
                message = ""
            raise SynthesisError(
                f"AI provider request failed: HTTP {error.code}: {message or body[:500] or error}"
            ) from error
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
            raise SynthesisError(f"AI provider request failed: {error}") from error


class ProviderAdapter(ABC):
    def __init__(
        self,
        config: ResolvedProviderConfig,
        transport: ProviderTransport | None = None,
        timeout_seconds: float = 60,
    ):
        self.config = config
        self.transport = transport or UrllibProviderTransport()
        self.timeout_seconds = timeout_seconds

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mathernet/1.0",
        }
        if self.config.auth_style == AUTH_X_API_KEY:
            headers["x-api-key"] = request.api_key
        else:
            headers["Authorization"] = f"Bearer {request.api_key}"
        self.with_auth_headers(headers, request)
        payload = self.transport.post(
            self.config.endpoint,
            headers,
            self.build_request_payload(request),
            self.timeout_seconds,
        )
        return ProviderResponse(
            text=extract_provider_text(payload),
            raw=payload,
            request_id=str(payload.get("id", "")),
            model=str(payload.get("model", request.model)),
        )

    @abstractmethod
    def build_request_payload(self, request: ProviderRequest) -> dict[str, Any]: ...

    def with_auth_headers(self, headers: dict[str, str], request: ProviderRequest) -> None:
        return


class AnthropicMessagesAdapter(ProviderAdapter):
    def build_request_payload(self, request: ProviderRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": 1200,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": request.user_prompt or request.system_prompt}],
            "temperature": request.temperature,
        }
        if request.json_schema is not None:
            payload["tools"] = [{
                "name": "save_formula_card",
                "description": "Save the validated formula card.",
                "input_schema": request.json_schema,
            }]
            payload["tool_choice"] = {"type": "tool", "name": "save_formula_card"}
        return payload

    def with_auth_headers(self, headers: dict[str, str], request: ProviderRequest) -> None:
        headers["anthropic-version"] = "2023-06-01"


class OpenAIChatAdapter(ProviderAdapter):
    def build_request_payload(self, request: ProviderRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt or request.system_prompt},
            ],
            "temperature": request.temperature,
        }
        if request.json_schema is not None:
            payload["response_format"] = {"type": "json_object"}
        return payload


class OpenAIResponsesAdapter(ProviderAdapter):
    def build_request_payload(self, request: ProviderRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "instructions": request.system_prompt,
            "input": request.user_prompt or request.system_prompt,
        }
        if request.json_schema is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "mathernet_formula_card",
                    "strict": True,
                    "schema": request.json_schema,
                }
            }
        return payload


ADAPTERS: dict[str, type[ProviderAdapter]] = {
    API_FORMAT_ANTHROPIC_MESSAGES: AnthropicMessagesAdapter,
    API_FORMAT_OPENAI_CHAT: OpenAIChatAdapter,
    API_FORMAT_OPENAI_RESPONSES: OpenAIResponsesAdapter,
}


def provider_catalog() -> list[dict[str, str]]:
    return [
        {
            "id": provider,
            "label": preset.label,
            "api_format": preset.api_format,
            "base_url": preset.base_url,
            "endpoint_path": preset.endpoint_path,
            "auth_style": preset.auth_style,
            "default_model": preset.default_model,
        }
        for provider, preset in PROVIDER_PRESETS.items()
    ]


def resolve_provider_config(
    provider: str,
    api_key: str,
    model: str,
    api_format: str = "",
    base_url: str = "",
    endpoint_path: str = "",
    auth_style: str = "",
) -> ResolvedProviderConfig:
    provider = provider.strip().lower()
    preset = PROVIDER_PRESETS.get(provider)
    resolved_format = api_format.strip() or (preset.api_format if preset else "")
    resolved_base_url = base_url.strip() or (preset.base_url if preset else "")
    resolved_endpoint_path = endpoint_path.strip() or (preset.endpoint_path if preset else "")
    resolved_auth_style = auth_style.strip() or (preset.auth_style if preset else "")
    resolved_model = model.strip() or (preset.default_model if preset else "")

    missing = [
        name
        for name, value in (
            ("api_format", resolved_format),
            ("base_url", resolved_base_url),
            ("endpoint_path", resolved_endpoint_path),
            ("auth_style", resolved_auth_style),
        )
        if not value
    ]
    if missing:
        raise ValidationError(f"provider configuration is missing: {', '.join(missing)}")
    if resolved_format not in API_FORMATS:
        raise ValidationError(f"unsupported provider API format: {resolved_format}")
    if resolved_auth_style not in AUTH_STYLES:
        raise ValidationError(f"unsupported provider auth style: {resolved_auth_style}")
    if not resolved_base_url.startswith(("https://", "http://")):
        raise ValidationError("provider base URL must use http or https")

    return ResolvedProviderConfig(
        provider=provider,
        api_key=api_key.strip(),
        model=resolved_model,
        api_format=resolved_format,
        base_url=resolved_base_url,
        endpoint_path=resolved_endpoint_path,
        auth_style=resolved_auth_style,
    )


def adapter_for_config(
    config: ResolvedProviderConfig,
    transport: ProviderTransport | None = None,
    timeout_seconds: float = 60,
) -> ProviderAdapter:
    adapter_type = ADAPTERS.get(config.api_format)
    if adapter_type is None:
        raise ValidationError(f"unsupported provider API format: {config.api_format}")
    return adapter_type(config, transport=transport, timeout_seconds=timeout_seconds)


def extract_provider_text(payload: dict[str, Any]) -> str:
    content_text = extract_content_text(payload.get("content"))
    if content_text:
        return content_text
    choices = payload.get("choices", [])
    if isinstance(choices, list) and choices:
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message", {})
        if isinstance(message, dict):
            choice_text = extract_content_text(message.get("content"))
            if choice_text:
                return choice_text
            tool_calls = message.get("tool_calls", [])
            tool_text = extract_content_text(tool_calls)
            if tool_text:
                return tool_text
        if isinstance(choice.get("text"), str):
            return choice["text"]
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    chunks: list[str] = []
    output = payload.get("output", [])
    for item in output if isinstance(output, list) else []:
        if not isinstance(item, dict):
            continue
        chunks.append(extract_content_text(item.get("content")))
    if chunks:
        return "".join(chunk for chunk in chunks if chunk)
    raise SynthesisError("AI provider response did not contain text")


def extract_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for item in content:
        if isinstance(item, str):
            chunks.append(item)
            continue
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("text"), str):
            chunks.append(item["text"])
        if item.get("type") in {"tool_use", "tool_call"} and isinstance(item.get("input"), dict):
            chunks.append(json.dumps(item["input"], ensure_ascii=False))
        function = item.get("function")
        if isinstance(function, dict) and isinstance(function.get("arguments"), str):
            chunks.append(function["arguments"])
    return "".join(chunks)
