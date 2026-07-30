from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from ai.client import OllamaClient, OpenAIClient, create_ai_client
from ai.models import AIAPIStyleChoices
from crm.models import RoleChoices


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def inbound_stub():
    return SimpleNamespace(
        id=1,
        source_type="site",
        source_name="site",
        message_text="Хочу купить автомобиль в кредит",
        name_raw="Lead",
        phone_raw="+7 999 100-00-00",
        email_raw="lead@example.test",
    )


def openai_response_content() -> str:
    return json.dumps(
        {
            "topic": "кредит на автомобиль",
            "need": "подбор автомобиля в кредит",
            "urgency": "high",
            "category": "credit",
            "spam_probability": 0.05,
            "toxicity": 0.0,
            "troll_probability": 0.0,
            "off_topic_probability": 0.0,
            "moderation_labels": [],
            "department": "finance",
            "ai_suggested_employee_id": None,
            "summary": "Клиент интересуется покупкой автомобиля в кредит.",
            "suggested_reply": "Здравствуйте! Уточните желаемую модель и бюджет, подберем варианты.",
        },
        ensure_ascii=False,
    )


class AIClientFactoryTests(TestCase):
    @override_settings(AI_PROVIDER="ollama")
    def test_factory_returns_ollama_client_by_default(self):
        self.assertIsInstance(create_ai_client(), OllamaClient)

    @override_settings(AI_PROVIDER="openai", OPENAI_API_KEY="test-key")
    def test_factory_returns_openai_client(self):
        self.assertIsInstance(create_ai_client(), OpenAIClient)


class OpenAIClientTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        user_model.objects.create_user(username="manager", password="secret", full_name="Manager", role=RoleChoices.MANAGER)

    @override_settings(OPENAI_API_KEY="test-key", OPENAI_BASE_URL="https://api.openai.test/v1", OPENAI_MODEL="test-model")
    def test_openai_client_uses_structured_outputs_and_validates_response(self):
        captured = {}

        def fake_post(url, *, json, headers, timeout):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            captured["timeout"] = timeout
            return FakeResponse({"choices": [{"message": {"content": openai_response_content()}}]})

        with (
            patch("ai.client.httpx.post", side_effect=fake_post),
            patch("ai.prompt.retrieve_knowledge_context", return_value="FAQ: кредит без первоначального взноса"),
        ):
            analysis = OpenAIClient().analyze(inbound=inbound_stub())

        self.assertEqual(captured["url"], "https://api.openai.test/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(captured["json"]["model"], "test-model")
        self.assertEqual(captured["json"]["response_format"]["type"], "json_schema")
        self.assertTrue(captured["json"]["response_format"]["json_schema"]["strict"])
        self.assertIn("FAQ: кредит без первоначального взноса", captured["json"]["messages"][1]["content"])
        self.assertIn('"is_follow_up": false', captured["json"]["messages"][1]["content"])
        self.assertEqual(analysis.category, "credit")
        self.assertEqual(analysis.department, "finance")
        self.assertTrue(analysis.suggested_reply)

    @override_settings(OPENAI_API_KEY="test-key", OPENAI_BASE_URL="https://bridge.test/v1", OPENAI_MODEL="bridge-model")
    def test_openai_client_can_use_responses_api_style(self):
        captured = {}

        def fake_post(url, *, json, headers, timeout):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            captured["timeout"] = timeout
            return FakeResponse({"output_text": openai_response_content()})

        with (
            patch("ai.client.httpx.post", side_effect=fake_post),
            patch("ai.prompt.retrieve_knowledge_context", return_value="Каталог: Haval Jolion"),
        ):
            analysis = OpenAIClient(api_style=AIAPIStyleChoices.RESPONSES).analyze(inbound=inbound_stub())

        self.assertEqual(captured["url"], "https://bridge.test/v1/responses")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(captured["json"]["model"], "bridge-model")
        self.assertEqual(captured["json"]["text"]["format"]["type"], "json_schema")
        self.assertIn("Каталог: Haval Jolion", captured["json"]["input"][1]["content"])
        self.assertEqual(analysis.category, "credit")
