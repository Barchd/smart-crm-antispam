"""AI model HTTP clients."""

from __future__ import annotations

import json
from typing import Any

import httpx
from django.conf import settings

from .config import get_ai_provider_config
from .models import AIAPIStyleChoices, AIProviderChoices
from .prompt import build_messages
from .schemas import RESPONSE_SCHEMA, AIAnalysis, AIResponseInvalid, validate_ai_payload


class AIModelUnavailable(RuntimeError):
    """Raised for transport errors, invalid JSON or invalid model output."""


class OllamaClient:
    """Small wrapper around Ollama chat API."""

    def __init__(self, *, base_url: str | None = None, model: str | None = None, timeout: float = 60.0):
        self.base_url = (base_url or settings.OLLAMA_URL).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.timeout = timeout

    def analyze(self, *, inbound) -> AIAnalysis:
        """Send one request to Ollama and validate the response."""

        payload = {
            "model": self.model,
            "messages": build_messages(inbound=inbound),
            "stream": False,
            "format": RESPONSE_SCHEMA,
            "think": False,
            "options": {"temperature": 0.1},
        }
        try:
            response = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
            response.raise_for_status()
            raw = response.json()
            content = raw.get("message", {}).get("content", "")
            parsed: dict[str, Any] = json.loads(content)
            return validate_ai_payload(parsed)
        except (httpx.HTTPError, json.JSONDecodeError, AIResponseInvalid, KeyError, TypeError) as exc:
            raise AIModelUnavailable("AI model unavailable or returned invalid output") from exc


class OpenAIClient:
    """Small wrapper around OpenAI Chat Completions with Structured Outputs."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        api_style: str = AIAPIStyleChoices.CHAT_COMPLETIONS,
        timeout: float = 60.0,
    ):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.base_url = (base_url or settings.OPENAI_BASE_URL).rstrip("/")
        self.model = model or settings.OPENAI_MODEL
        self.api_style = api_style
        self.timeout = timeout

    def analyze(self, *, inbound) -> AIAnalysis:
        """Send one request to OpenAI and validate the structured response."""

        if not self.api_key:
            raise AIModelUnavailable("OPENAI_API_KEY is not configured")

        payload = {
            "model": self.model,
            "messages": build_messages(inbound=inbound),
            "temperature": 0.1,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "crm_lead_analysis",
                    "strict": True,
                    "schema": RESPONSE_SCHEMA,
                },
            },
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            if self.api_style == AIAPIStyleChoices.RESPONSES:
                response = httpx.post(f"{self.base_url}/responses", json=self._responses_payload(inbound=inbound), headers=headers, timeout=self.timeout)
            else:
                response = httpx.post(f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            raw = response.json()
            content = self._extract_content(raw)
            parsed: dict[str, Any] = json.loads(content)
            return validate_ai_payload(parsed)
        except (httpx.HTTPError, json.JSONDecodeError, AIResponseInvalid, KeyError, IndexError, TypeError) as exc:
            raise AIModelUnavailable("AI model unavailable or returned invalid output") from exc

    def _responses_payload(self, *, inbound) -> dict[str, Any]:
        return {
            "model": self.model,
            "input": build_messages(inbound=inbound),
            "temperature": 0.1,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "crm_lead_analysis",
                    "strict": True,
                    "schema": RESPONSE_SCHEMA,
                }
            },
        }

    def _extract_content(self, raw: dict[str, Any]) -> str:
        if self.api_style == AIAPIStyleChoices.RESPONSES:
            if raw.get("output_text"):
                return raw["output_text"]
            for item in raw.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") in {"output_text", "text"} and content.get("text"):
                        return content["text"]
            raise KeyError("output_text")
        return raw["choices"][0]["message"]["content"]


def create_ai_client():
    """Create the configured AI provider client."""

    config = get_ai_provider_config()
    if config.provider == AIProviderChoices.OLLAMA:
        return OllamaClient(base_url=config.ollama_url, model=config.ollama_model)
    if config.provider == AIProviderChoices.OPENAI:
        return OpenAIClient(
            api_key=config.openai_api_key,
            base_url=config.openai_base_url,
            model=config.openai_model,
            api_style=config.openai_api_style,
        )
    raise AIModelUnavailable(f"Unsupported AI provider: {config.provider}")
