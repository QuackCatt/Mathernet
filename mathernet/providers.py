from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import SynthesisError, ValidationError
from .http_client import open_url


API_FORMAT_OPENAI_CHAT = "openai_chat"

AUTH_BEARER = "bearer"

API_FORMATS = (API_FORMAT_OPENAI_CHAT,)
AUTH_STYLES = (AUTH_BEARER,)


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    label: str
    api_format: str
    base_url: str
    endpoint_path: str
    auth_style: str
    default_model: str
    model_required: bool
    managed_model: bool
    models_endpoint_path: str
    description: str
    website_url: str
    api_key_url: str
    structured_json: bool


PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "deepseek": ProviderPreset(
        label="DeepSeek",
        api_format=API_FORMAT_OPENAI_CHAT,
        base_url="https://api.deepseek.com",
        endpoint_path="/v1/chat/completions",
        auth_style=AUTH_BEARER,
        default_model="deepseek-chat",
        model_required=False,
        managed_model=True,
        models_endpoint_path="",
        description="DeepSeek's official OpenAI-compatible API. Mathernet manages the default chat model.",
        website_url="https://platform.deepseek.com",
        api_key_url="https://platform.deepseek.com/api_keys",
        structured_json=True,
    ),
    "openrouter": ProviderPreset(
        label="OpenRouter",
        api_format=API_FORMAT_OPENAI_CHAT,
        base_url="https://openrouter.ai",
        endpoint_path="/api/v1/chat/completions",
        auth_style=AUTH_BEARER,
        default_model="openai/gpt-4o-mini",
        model_required=True,
        managed_model=False,
        models_endpoint_path="/api/v1/models",
        description="OpenRouter routes requests to a model you choose. Use a provider/model route ID.",
        website_url="https://openrouter.ai",
        api_key_url="https://openrouter.ai/keys",
        structured_json=False,
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
    structured_json: bool

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
        retry_attempts: int = 1,
        retry_delay_seconds: float = 0.75,
    ):
        self.config = config
        self.transport = transport or UrllibProviderTransport()
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = max(0, retry_attempts)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        for attempt in range(self.retry_attempts + 1):
            try:
                return self.complete_once(request)
            except SynthesisError as error:
                if attempt >= self.retry_attempts or not is_transient_provider_error(error):
                    raise
                time.sleep(self.retry_delay_seconds * (2**attempt))
        raise SynthesisError("AI provider request failed after retrying")

    def complete_once(self, request: ProviderRequest) -> ProviderResponse:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mathernet/1.0",
        }
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


class OpenAIChatAdapter(ProviderAdapter):
    def build_request_payload(self, request: ProviderRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt or request.system_prompt},
            ],
            "temperature": request.temperature,
            "max_tokens": 4096,
        }
        if request.json_schema is not None and self.config.structured_json:
            payload["response_format"] = {"type": "json_object"}
        if self.config.provider == "openrouter":
            payload["reasoning"] = {"effort": "medium"}
        return payload

    def with_auth_headers(self, headers: dict[str, str], request: ProviderRequest) -> None:
        if self.config.provider == "openrouter":
            headers["HTTP-Referer"] = "http://127.0.0.1"
            headers["X-Title"] = "Mathernet"


ADAPTERS: dict[str, type[ProviderAdapter]] = {
    API_FORMAT_OPENAI_CHAT: OpenAIChatAdapter,
}


def provider_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": provider,
            "label": preset.label,
            "api_format": preset.api_format,
            "base_url": preset.base_url,
            "endpoint_path": preset.endpoint_path,
            "auth_style": preset.auth_style,
            "default_model": preset.default_model,
            "model_required": preset.model_required,
            "managed_model": preset.managed_model,
            "models_endpoint_path": preset.models_endpoint_path,
            "description": preset.description,
            "website_url": preset.website_url,
            "api_key_url": preset.api_key_url,
            "structured_json": preset.structured_json,
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
    if not preset:
        raise ValidationError(f"unsupported AI provider: {provider or 'empty'}")
    resolved_format = api_format.strip() or (preset.api_format if preset else "")
    resolved_base_url = base_url.strip() or (preset.base_url if preset else "")
    resolved_endpoint_path = endpoint_path.strip() or (preset.endpoint_path if preset else "")
    resolved_auth_style = auth_style.strip() or (preset.auth_style if preset else "")
    resolved_model = (
        preset.default_model
        if preset.managed_model
        else model.strip()
    )

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
    if preset.model_required and not resolved_model:
        raise ValidationError("model is required for this AI provider")

    return ResolvedProviderConfig(
        provider=provider,
        api_key=api_key.strip(),
        model=resolved_model,
        api_format=resolved_format,
        base_url=resolved_base_url,
        endpoint_path=resolved_endpoint_path,
        auth_style=resolved_auth_style,
        structured_json=preset.structured_json,
    )


def adapter_for_config(
    config: ResolvedProviderConfig,
    transport: ProviderTransport | None = None,
    timeout_seconds: float = 60,
    retry_attempts: int = 1,
    retry_delay_seconds: float = 0.75,
) -> ProviderAdapter:
    adapter_type = ADAPTERS.get(config.api_format)
    if adapter_type is None:
        raise ValidationError(f"unsupported provider API format: {config.api_format}")
    return adapter_type(
        config,
        transport=transport,
        timeout_seconds=timeout_seconds,
        retry_attempts=retry_attempts,
        retry_delay_seconds=retry_delay_seconds,
    )


def is_transient_provider_error(error: Exception) -> bool:
    message = str(error).casefold()
    return any(
        marker in message
        for marker in (
            "temporarily",
            "overloaded",
            "unavailable",
            "rate limit",
            "timeout",
            "timed out",
            "connection reset",
            "http 429",
            "http 502",
            "http 503",
            "http 504",
            "did not contain final text",
        )
    )


def fetch_provider_models(
    provider: str,
    api_key: str,
    *,
    timeout: float = 30,
) -> list[dict[str, str]]:
    provider = provider.strip().lower()
    preset = PROVIDER_PRESETS.get(provider)
    if not preset:
        raise ValidationError(f"unsupported AI provider: {provider or 'empty'}")
    if not preset.models_endpoint_path:
        return [{
            "id": preset.default_model,
            "name": preset.default_model,
            "managed": "true",
        }]
    if not api_key.strip():
        raise ValidationError("API key is required to load provider models")
    endpoint = f"{preset.base_url.rstrip('/')}/{preset.models_endpoint_path.lstrip('/')}"
    request = urllib.request.Request(
        endpoint,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key.strip()}",
            "User-Agent": "Mathernet/1.0",
            "HTTP-Referer": "http://127.0.0.1",
            "X-Title": "Mathernet",
        },
        method="GET",
    )
    try:
        with open_url(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
        raise SynthesisError(f"AI provider model request failed: {error}") from error
    raw_models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw_models, list):
        raise SynthesisError("AI provider model response did not contain a model list")
    models: list[dict[str, str]] = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or item.get("name") or "").strip()
        if model_id:
            models.append({
                "id": model_id,
                "name": str(item.get("name") or model_id).strip(),
                "managed": "false",
            })
    return sorted(models, key=lambda item: item["id"].casefold())


def extract_provider_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("error"), dict):
        error = payload["error"]
        message = error.get("message") or error.get("code") or "unknown provider error"
        raise SynthesisError(f"AI provider response failed: {message}")
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
            reasoning_text = extract_content_text(
                message.get("reasoning_content") or message.get("reasoning")
            )
            if reasoning_text:
                return reasoning_text
            reasoning_details = message.get("reasoning_details")
            detail_text = extract_reasoning_details(reasoning_details)
            if detail_text:
                return detail_text
        if isinstance(choice.get("text"), str):
            return choice["text"]
        delta_text = extract_content_text(choice.get("delta"))
        if delta_text:
            return delta_text
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
    finish_reason = choices[0].get("finish_reason") if choices and isinstance(choices[0], dict) else ""
    detail = f" (finish_reason={finish_reason})" if finish_reason else ""
    raise SynthesisError(f"AI provider response did not contain final text{detail}")


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
        if isinstance(item.get("content"), str):
            chunks.append(item["content"])
        if isinstance(item.get("output_text"), str):
            chunks.append(item["output_text"])
        if isinstance(item.get("summary"), str) and not item.get("text"):
            chunks.append(item["summary"])
        if item.get("type") in {"tool_use", "tool_call"} and isinstance(item.get("input"), dict):
            chunks.append(json.dumps(item["input"], ensure_ascii=False))
        function = item.get("function")
        if isinstance(function, dict) and isinstance(function.get("arguments"), str):
            chunks.append(function["arguments"])
    return "".join(chunks)


def extract_reasoning_details(details: Any) -> str:
    if not isinstance(details, list):
        return ""
    chunks: list[str] = []
    for item in details:
        if isinstance(item, str):
            chunks.append(item)
            continue
        if not isinstance(item, dict):
            continue
        text = item.get("text") or item.get("content") or item.get("summary")
        if isinstance(text, str):
            chunks.append(text)
    return "".join(chunks)
