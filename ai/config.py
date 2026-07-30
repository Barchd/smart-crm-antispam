"""Helpers for reading and checking AI provider settings."""

from __future__ import annotations

from dataclasses import dataclass

import re

import httpx
from django.conf import settings
from django.db import OperationalError, ProgrammingError

from .models import AIAPIStyleChoices, AIConnectionStatusChoices, AIProviderChoices, AISettings


@dataclass(frozen=True)
class AIProviderConfig:
    """Runtime AI provider configuration."""

    provider: str
    connection_type: str
    ollama_url: str
    ollama_model: str
    openai_base_url: str
    openai_model: str
    openai_api_style: str
    openai_transcription_model: str
    openai_api_key: str


@dataclass(frozen=True)
class ConnectionCheckResult:
    """User-facing result of an AI provider connection check."""

    ok: bool
    message: str


def mask_secret(value: str) -> str:
    """Return a short non-sensitive mask for UI display."""

    if not value:
        return ""
    tail = value[-4:] if len(value) >= 4 else "****"
    return f"***{tail}"


def sanitize_provider_error(message: str, secret: str = "") -> str:
    """Remove configured secrets from provider error messages."""

    if secret:
        message = re.sub(re.escape(secret), "***", message)
    return message


def get_ai_provider_config() -> AIProviderConfig:
    """Read DB settings with env fallback before migrations are available."""

    try:
        current = AISettings.current()
    except (OperationalError, ProgrammingError):
        return AIProviderConfig(
            provider=settings.AI_PROVIDER,
            connection_type=AISettings.connection_type_from_env(),
            ollama_url=settings.OLLAMA_URL,
            ollama_model=settings.OLLAMA_MODEL,
            openai_base_url=settings.OPENAI_BASE_URL,
            openai_model=settings.OPENAI_MODEL,
            openai_api_style=AIAPIStyleChoices.CHAT_COMPLETIONS,
            openai_transcription_model=settings.OPENAI_TRANSCRIPTION_MODEL,
            openai_api_key=settings.OPENAI_API_KEY or "",
        )

    return AIProviderConfig(
        provider=current.provider,
        connection_type=current.connection_type,
        ollama_url=current.ollama_url,
        ollama_model=current.ollama_model,
        openai_base_url=current.openai_base_url,
        openai_model=current.openai_model,
        openai_api_style=current.openai_api_style,
        openai_transcription_model=current.openai_transcription_model,
        openai_api_key=current.openai_api_key,
    )


def check_ai_connection(config: AIProviderConfig | None = None, *, timeout: float = 10.0) -> ConnectionCheckResult:
    """Check provider availability without sending lead text."""

    cfg = config or get_ai_provider_config()
    if cfg.provider == AIProviderChoices.OLLAMA:
        return check_ollama_connection(base_url=cfg.ollama_url, model=cfg.ollama_model, timeout=timeout)
    if cfg.provider == AIProviderChoices.OPENAI:
        return check_openai_connection(
            base_url=cfg.openai_base_url,
            model=cfg.openai_model,
            api_key=cfg.openai_api_key,
            api_style=cfg.openai_api_style,
            connection_type=cfg.connection_type,
            timeout=timeout,
        )
    return ConnectionCheckResult(ok=False, message=f"Неизвестный AI provider: {cfg.provider}")


def check_ollama_connection(*, base_url: str, model: str, timeout: float = 10.0) -> ConnectionCheckResult:
    """Check Ollama tags endpoint and whether the configured model exists."""

    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return ConnectionCheckResult(ok=False, message=f"Ollama недоступен: {exc}")

    models = payload.get("models", []) if isinstance(payload, dict) else []
    names = {item.get("name") for item in models if isinstance(item, dict)}
    if model in names:
        return ConnectionCheckResult(ok=True, message=f"Ollama доступен, модель {model} найдена")
    return ConnectionCheckResult(ok=False, message=f"Ollama доступен, но модель {model} не найдена")


def check_openai_connection(
    *,
    base_url: str,
    model: str,
    api_key: str,
    api_style: str = AIAPIStyleChoices.CHAT_COMPLETIONS,
    connection_type: str = "",
    timeout: float = 10.0,
) -> ConnectionCheckResult:
    """Check OpenAI-compatible model access and quota with a tiny chat request."""

    if not api_key:
        return ConnectionCheckResult(ok=False, message="OpenAI API key не задан")
    if connection_type and connection_type != "openai_official":
        return _check_openai_generation_endpoint(
            base_url=base_url,
            model=model,
            api_key=api_key,
            api_style=api_style,
            timeout=timeout,
        )

    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=timeout)
        if response.status_code >= 400:
            return ConnectionCheckResult(ok=False, message=f"OpenAI недоступен: {_format_openai_error(response, api_key)}")
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        sanitized = sanitize_provider_error(str(exc), api_key)
        return ConnectionCheckResult(ok=False, message=f"OpenAI недоступен: {sanitized}")

    models = payload.get("data", []) if isinstance(payload, dict) else []
    ids = {item.get("id") for item in models if isinstance(item, dict)}
    if not ids or model in ids:
        return _check_openai_generation_endpoint(
            base_url=base_url,
            model=model,
            api_key=api_key,
            api_style=api_style,
            timeout=timeout,
        )
    return ConnectionCheckResult(ok=False, message=f"OpenAI доступен, но модель {model} не найдена")


def _check_openai_generation_endpoint(*, base_url: str, model: str, api_key: str, api_style: str, timeout: float = 10.0) -> ConnectionCheckResult:
    if api_style == AIAPIStyleChoices.RESPONSES:
        return check_openai_responses_model_connection(base_url=base_url, model=model, api_key=api_key, timeout=timeout)
    return check_openai_chat_model_connection(base_url=base_url, model=model, api_key=api_key, timeout=timeout)


def check_openai_chat_model_connection(*, base_url: str, model: str, api_key: str, timeout: float = 10.0) -> ConnectionCheckResult:
    """Run a minimal chat completion to catch quota/billing/model errors."""

    if not api_key:
        return ConnectionCheckResult(ok=False, message="OpenAI API key не задан")
    model = model.strip()
    if not model:
        return ConnectionCheckResult(ok=False, message="Название OpenAI модели не задано")

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_completion_tokens": 1,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = httpx.post(f"{base_url.rstrip('/')}/chat/completions", json=payload, headers=headers, timeout=timeout)
        if response.status_code >= 400:
            return ConnectionCheckResult(ok=False, message=f"OpenAI chat-модель {model} недоступна: {_format_openai_error(response, api_key)}")
        response.json()
    except (httpx.HTTPError, ValueError) as exc:
        sanitized = sanitize_provider_error(str(exc), api_key)
        return ConnectionCheckResult(ok=False, message=f"OpenAI chat-модель {model} недоступна: {sanitized}")
    return ConnectionCheckResult(ok=True, message=f"OpenAI chat-модель {model} доступна, пробный запрос прошел")


def check_openai_responses_model_connection(*, base_url: str, model: str, api_key: str, timeout: float = 10.0) -> ConnectionCheckResult:
    """Run a minimal Responses API request to catch quota/billing/model errors."""

    if not api_key:
        return ConnectionCheckResult(ok=False, message="OpenAI API key не задан")
    model = model.strip()
    if not model:
        return ConnectionCheckResult(ok=False, message="Название OpenAI модели не задано")

    payload = {
        "model": model,
        "input": "ping",
        "max_output_tokens": 1,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = httpx.post(f"{base_url.rstrip('/')}/responses", json=payload, headers=headers, timeout=timeout)
        if response.status_code >= 400:
            return ConnectionCheckResult(ok=False, message=f"OpenAI Responses-модель {model} недоступна: {_format_openai_error(response, api_key)}")
        response.json()
    except (httpx.HTTPError, ValueError) as exc:
        sanitized = sanitize_provider_error(str(exc), api_key)
        return ConnectionCheckResult(ok=False, message=f"OpenAI Responses-модель {model} недоступна: {sanitized}")
    return ConnectionCheckResult(ok=True, message=f"OpenAI Responses-модель {model} доступна, пробный запрос прошел")


def record_ai_connection_check(settings_obj: AISettings, result: ConnectionCheckResult) -> None:
    """Persist the last safe connection check result for the settings dashboard."""

    from django.utils import timezone

    settings_obj.last_check_status = AIConnectionStatusChoices.OK if result.ok else AIConnectionStatusChoices.FAIL
    settings_obj.last_check_message = result.message[:500]
    settings_obj.last_checked_at = timezone.now()
    settings_obj.save(update_fields=["last_check_status", "last_check_message", "last_checked_at", "updated_at"])


def check_openai_model_list_access(*, base_url: str, model: str, api_key: str, timeout: float = 10.0) -> ConnectionCheckResult:
    """Check whether an OpenAI-compatible model is visible in /models."""

    if not api_key:
        return ConnectionCheckResult(ok=False, message="OpenAI API key не задан")
    model = model.strip()
    if not model:
        return ConnectionCheckResult(ok=False, message="Название OpenAI модели не задано")

    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=timeout)
        if response.status_code >= 400:
            return ConnectionCheckResult(ok=False, message=f"OpenAI /models недоступен: {_format_openai_error(response, api_key)}")
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        sanitized = sanitize_provider_error(str(exc), api_key)
        return ConnectionCheckResult(ok=False, message=f"OpenAI /models недоступен: {sanitized}")

    models = payload.get("data", []) if isinstance(payload, dict) else []
    ids = {item.get("id") for item in models if isinstance(item, dict)}
    if not ids or model in ids:
        return ConnectionCheckResult(ok=True, message=f"OpenAI модель {model} доступна в списке моделей")
    return ConnectionCheckResult(ok=False, message=f"OpenAI модель {model} не найдена в списке доступных моделей")


def _format_openai_error(response: httpx.Response, api_key: str) -> str:
    """Extract a safe useful OpenAI error message for CRM operators."""

    try:
        payload = response.json()
    except ValueError:
        return sanitize_provider_error(response.text or response.reason_phrase, api_key)

    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        parts = [str(error.get("message") or response.reason_phrase)]
        error_type = error.get("type")
        error_code = error.get("code")
        if error_type:
            parts.append(f"type={error_type}")
        if error_code:
            parts.append(f"code={error_code}")
        message = "; ".join(parts)
    else:
        message = response.text or response.reason_phrase

    return f"HTTP {response.status_code}: {sanitize_provider_error(message, api_key)}"
