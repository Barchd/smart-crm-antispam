from __future__ import annotations

from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from ai.client import OpenAIClient, create_ai_client
from ai.config import AIProviderConfig, ConnectionCheckResult, check_ai_connection, mask_secret
from ai.models import AIAPIStyleChoices, AIConnectionStatusChoices, AIConnectionTypeChoices, AIProviderChoices, AISettings
from crm.models import RoleChoices


class AISettingsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.head = user_model.objects.create_user(username="head", password="secret", full_name="Head", role=RoleChoices.HEAD)
        self.manager = user_model.objects.create_user(username="manager", password="secret", full_name="Manager", role=RoleChoices.MANAGER)

    def test_manager_cannot_open_ai_settings(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("ai_settings"))

        self.assertEqual(response.status_code, 403)

    def test_head_saves_openai_settings_without_rendering_key(self):
        self.client.force_login(self.head)

        response = self.client.post(
            reverse("ai_settings"),
            {
                "name": "OpenAI official",
                "connection_type": AIConnectionTypeChoices.OPENAI_OFFICIAL,
                "ollama_url": "http://127.0.0.1:11434",
                "ollama_model": "qwen3.5:9b",
                "openai_base_url": "https://api.openai.test/v1",
                "openai_model": "test-model",
                "openai_api_style": AIAPIStyleChoices.CHAT_COMPLETIONS,
                "openai_transcription_model": "transcribe-test",
                "openai_api_key_input": "sk-test-secret-value",
                "action": "save",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        settings_obj = AISettings.objects.get(name="OpenAI official")
        self.assertEqual(settings_obj.provider, AIProviderChoices.OPENAI)
        self.assertEqual(settings_obj.connection_type, AIConnectionTypeChoices.OPENAI_OFFICIAL)
        self.assertEqual(settings_obj.openai_base_url, "https://api.openai.com/v1")
        self.assertEqual(settings_obj.openai_api_style, AIAPIStyleChoices.CHAT_COMPLETIONS)
        self.assertEqual(settings_obj.openai_api_key, "sk-test-secret-value")
        self.assertContains(response, mask_secret("sk-test-secret-value"))
        self.assertNotContains(response, "sk-test-secret-value")

    def test_head_checks_existing_ai_settings_without_resubmitting_form(self):
        self.client.force_login(self.head)
        AISettings.objects.create(
            pk=1,
            provider=AIProviderChoices.OLLAMA,
            ollama_url="http://ollama.test",
            ollama_model="qwen3.5:9b",
        )

        with patch("ai.views.check_ai_connection", return_value=ConnectionCheckResult(ok=True, message="Ollama доступен")) as check:
            response = self.client.post(reverse("ai_settings"), {"action": "check_current"}, follow=True)

        self.assertEqual(response.status_code, 200)
        check.assert_called_once()
        self.assertContains(response, "Ollama доступен")

    def test_ai_settings_page_has_current_check_and_delete_controls(self):
        self.client.force_login(self.head)

        response = self.client.get(reverse("ai_settings"))

        self.assertContains(response, "Подключения разделены")
        self.assertContains(response, "Проверить подключение")
        self.assertContains(response, "Добавить подключение")
        self.assertContains(response, "Тип подключения")
        self.assertContains(response, "OpenAI-compatible")
        self.assertContains(response, "По умолчанию", count=0)

    def test_head_creates_separate_connection_without_changing_existing_default(self):
        self.client.force_login(self.head)
        default_connection = AISettings.current()

        response = self.client.post(
            reverse("ai_settings"),
            {
                "name": "Custom bridge",
                "connection_type": AIConnectionTypeChoices.OPENAI_COMPATIBLE,
                "ollama_url": "http://127.0.0.1:11434",
                "ollama_model": "qwen3.5:9b",
                "openai_base_url": "https://bridge.test/v1",
                "openai_model": "bridge-model",
                "openai_api_style": AIAPIStyleChoices.RESPONSES,
                "openai_transcription_model": "gpt-transcribe",
                "openai_api_key_input": "bridge-key",
                "action": "save",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AISettings.objects.count(), 2)
        self.assertEqual(AISettings.current().pk, default_connection.pk)
        custom = AISettings.objects.get(name="Custom bridge")
        self.assertFalse(custom.is_default)
        self.assertEqual(custom.openai_api_style, AIAPIStyleChoices.RESPONSES)

    def test_head_can_make_connection_default(self):
        self.client.force_login(self.head)
        first = AISettings.current()
        second = AISettings.objects.create(
            name="Custom bridge",
            provider=AIProviderChoices.OPENAI,
            connection_type=AIConnectionTypeChoices.OPENAI_COMPATIBLE,
            openai_base_url="https://bridge.test/v1",
            openai_model="bridge-model",
            openai_api_style=AIAPIStyleChoices.RESPONSES,
            openai_api_key="bridge-key",
        )

        response = self.client.post(reverse("ai_connection_default", kwargs={"pk": second.pk}), follow=True)

        self.assertEqual(response.status_code, 200)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)
        self.assertEqual(AISettings.current().pk, second.pk)

    def test_head_checks_one_connection_without_touching_another(self):
        self.client.force_login(self.head)
        default_connection = AISettings.current()
        custom = AISettings.objects.create(
            name="Custom bridge",
            provider=AIProviderChoices.OPENAI,
            connection_type=AIConnectionTypeChoices.OPENAI_COMPATIBLE,
            openai_base_url="https://bridge.test/v1",
            openai_model="bridge-model",
            openai_api_style=AIAPIStyleChoices.RESPONSES,
            openai_api_key="bridge-key",
        )

        with patch("ai.views.check_ai_connection", return_value=ConnectionCheckResult(ok=True, message="custom ok")):
            response = self.client.post(reverse("ai_connection_check", kwargs={"pk": custom.pk}), follow=True)

        self.assertEqual(response.status_code, 200)
        default_connection.refresh_from_db()
        custom.refresh_from_db()
        self.assertEqual(default_connection.last_check_status, AIConnectionStatusChoices.UNKNOWN)
        self.assertEqual(custom.last_check_status, AIConnectionStatusChoices.OK)

    def test_head_deletes_one_connection_and_preserves_default(self):
        self.client.force_login(self.head)
        default_connection = AISettings.current()
        custom = AISettings.objects.create(
            name="Custom bridge",
            provider=AIProviderChoices.OPENAI,
            connection_type=AIConnectionTypeChoices.OPENAI_COMPATIBLE,
            openai_base_url="https://bridge.test/v1",
            openai_model="bridge-model",
            openai_api_key="bridge-key",
        )

        response = self.client.post(reverse("ai_connection_delete", kwargs={"pk": custom.pk}), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(AISettings.objects.filter(pk=custom.pk).exists())
        self.assertEqual(AISettings.current().pk, default_connection.pk)

    def test_manager_cannot_use_connection_actions(self):
        self.client.force_login(self.manager)
        connection = AISettings.current()

        self.assertEqual(self.client.post(reverse("ai_connection_check", kwargs={"pk": connection.pk})).status_code, 403)
        self.assertEqual(self.client.post(reverse("ai_connection_default", kwargs={"pk": connection.pk})).status_code, 403)
        self.assertEqual(self.client.post(reverse("ai_connection_delete", kwargs={"pk": connection.pk})).status_code, 403)

    @override_settings(
        AI_PROVIDER=AIProviderChoices.OLLAMA,
        OLLAMA_URL="http://env-ollama.test",
        OLLAMA_MODEL="env-model",
        OPENAI_API_KEY="",
    )
    def test_head_deletes_saved_ai_settings(self):
        self.client.force_login(self.head)
        AISettings.objects.create(
            pk=1,
            provider=AIProviderChoices.OPENAI,
            ollama_url="http://127.0.0.1:11434",
            ollama_model="qwen3.5:9b",
            openai_base_url="https://api.openai.test/v1",
            openai_model="test-model",
            openai_transcription_model="transcribe-test",
            openai_api_key="sk-test-secret-value",
        )

        response = self.client.post(reverse("ai_settings_delete"), follow=False)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AISettings.objects.exists())

    def test_manager_cannot_delete_ai_settings(self):
        self.client.force_login(self.manager)

        response = self.client.post(reverse("ai_settings_delete"))

        self.assertEqual(response.status_code, 403)

    @override_settings(
        OPENAI_BASE_URL="https://api.openai.com/v1",
        OPENAI_MODEL="gpt-5.6-sol",
        OPENAI_TRANSCRIPTION_MODEL="gpt-transcribe",
    )
    def test_head_deletes_openai_connection_without_deleting_ollama_settings(self):
        self.client.force_login(self.head)
        AISettings.objects.create(
            pk=1,
            provider=AIProviderChoices.OPENAI,
            ollama_url="http://local-ollama.test",
            ollama_model="local-model",
            openai_base_url="https://api.openai.test/v1",
            openai_model="paid-model",
            openai_transcription_model="paid-transcribe",
            openai_api_key="sk-test-secret-value",
        )

        response = self.client.post(reverse("ai_openai_delete"), follow=True)

        self.assertEqual(response.status_code, 200)
        settings_obj = AISettings.current()
        self.assertEqual(settings_obj.provider, AIProviderChoices.OLLAMA)
        self.assertEqual(settings_obj.connection_type, AIConnectionTypeChoices.OLLAMA)
        self.assertEqual(settings_obj.ollama_url, "http://local-ollama.test")
        self.assertEqual(settings_obj.ollama_model, "local-model")
        self.assertEqual(settings_obj.openai_api_key, "")
        self.assertEqual(settings_obj.openai_base_url, "https://api.openai.com/v1")
        self.assertEqual(settings_obj.openai_model, "gpt-5.6-sol")
        self.assertEqual(settings_obj.openai_transcription_model, "gpt-transcribe")
        self.assertEqual(settings_obj.openai_api_style, AIAPIStyleChoices.CHAT_COMPLETIONS)
        self.assertEqual(settings_obj.last_check_status, AIConnectionStatusChoices.UNKNOWN)
        self.assertNotContains(response, "sk-test-secret-value")

    def test_manager_cannot_delete_openai_connection(self):
        self.client.force_login(self.manager)

        response = self.client.post(reverse("ai_openai_delete"))

        self.assertEqual(response.status_code, 403)

    def test_head_checks_openai_and_shows_quota_error_without_key_leak(self):
        self.client.force_login(self.head)
        AISettings.objects.create(
            pk=1,
            provider=AIProviderChoices.OPENAI,
            ollama_url="http://127.0.0.1:11434",
            ollama_model="qwen3.5:9b",
            openai_base_url="https://api.openai.test/v1",
            openai_model="test-model",
            openai_transcription_model="transcribe-test",
            openai_api_key="sk-sensitive",
        )
        models_request = httpx.Request("GET", "https://api.openai.test/v1/models")
        chat_request = httpx.Request("POST", "https://api.openai.test/v1/chat/completions")
        models_response = httpx.Response(200, json={"data": [{"id": "test-model"}]}, request=models_request)
        quota_response = httpx.Response(
            429,
            json={"error": {"message": "You exceeded your current quota", "type": "insufficient_quota", "code": "insufficient_quota"}},
            request=chat_request,
        )

        with patch("ai.config.httpx.get", return_value=models_response), patch("ai.config.httpx.post", return_value=quota_response):
            response = self.client.post(reverse("ai_settings"), {"action": "check_openai"}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You exceeded your current quota")
        self.assertContains(response, "insufficient_quota")
        self.assertNotContains(response, "sk-sensitive")
        settings_obj = AISettings.current()
        self.assertEqual(settings_obj.last_check_status, AIConnectionStatusChoices.FAIL)
        self.assertIn("insufficient_quota", settings_obj.last_check_message)

    def test_custom_responses_connection_check_skips_models_endpoint(self):
        config = AIProviderConfig(
            provider=AIProviderChoices.OPENAI,
            connection_type=AIConnectionTypeChoices.OPENAI_COMPATIBLE,
            ollama_url="http://127.0.0.1:11434",
            ollama_model="qwen3.5:9b",
            openai_base_url="https://bridge.test/v1",
            openai_model="bridge-model",
            openai_api_style=AIAPIStyleChoices.RESPONSES,
            openai_transcription_model="transcribe-test",
            openai_api_key="sk-sensitive",
        )
        response_request = httpx.Request("POST", "https://bridge.test/v1/responses")
        response = httpx.Response(200, json={"output_text": "ok"}, request=response_request)

        with patch("ai.config.httpx.get") as get, patch("ai.config.httpx.post", return_value=response) as post:
            result = check_ai_connection(config)

        self.assertTrue(result.ok)
        get.assert_not_called()
        post.assert_called_once()

    def test_head_checks_specific_openai_model(self):
        self.client.force_login(self.head)
        AISettings.objects.create(
            pk=1,
            provider=AIProviderChoices.OLLAMA,
            ollama_url="http://127.0.0.1:11434",
            ollama_model="qwen3.5:9b",
            openai_base_url="https://api.openai.test/v1",
            openai_model="default-model",
            openai_transcription_model="transcribe-test",
            openai_api_key="sk-sensitive",
        )

        with patch("ai.views.check_openai_chat_model_connection", return_value=ConnectionCheckResult(ok=True, message="custom-model ok")) as check:
            response = self.client.post(
                reverse("ai_settings"),
                {"action": "check_openai_model", "openai_check_model": "custom-model", "openai_check_kind": "chat"},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        check.assert_called_once_with(base_url="https://api.openai.test/v1", model="custom-model", api_key="sk-sensitive")
        self.assertContains(response, "custom-model ok")
        self.assertNotContains(response, "sk-sensitive")

    def test_head_checks_specific_openai_model_list_access(self):
        self.client.force_login(self.head)
        AISettings.objects.create(
            pk=1,
            provider=AIProviderChoices.OLLAMA,
            ollama_url="http://127.0.0.1:11434",
            ollama_model="qwen3.5:9b",
            openai_base_url="https://api.openai.test/v1",
            openai_model="default-model",
            openai_transcription_model="transcribe-test",
            openai_api_key="sk-sensitive",
        )

        with patch("ai.views.check_openai_model_list_access", return_value=ConnectionCheckResult(ok=True, message="transcribe-test visible")) as check:
            response = self.client.post(
                reverse("ai_settings"),
                {"action": "check_openai_model", "openai_check_model": "transcribe-test", "openai_check_kind": "list"},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        check.assert_called_once_with(base_url="https://api.openai.test/v1", model="transcribe-test", api_key="sk-sensitive")
        self.assertContains(response, "transcribe-test visible")

    def test_head_checks_specific_openai_responses_model(self):
        self.client.force_login(self.head)
        AISettings.objects.create(
            pk=1,
            provider=AIProviderChoices.OPENAI,
            connection_type=AIConnectionTypeChoices.OPENAI_COMPATIBLE,
            ollama_url="http://127.0.0.1:11434",
            ollama_model="qwen3.5:9b",
            openai_base_url="https://bridge.test/v1",
            openai_model="default-model",
            openai_api_style=AIAPIStyleChoices.RESPONSES,
            openai_transcription_model="transcribe-test",
            openai_api_key="sk-sensitive",
        )

        with patch("ai.views.check_openai_responses_model_connection", return_value=ConnectionCheckResult(ok=True, message="responses ok")) as check:
            response = self.client.post(
                reverse("ai_settings"),
                {"action": "check_openai_model", "openai_check_model": "custom-model", "openai_check_kind": "responses"},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        check.assert_called_once_with(base_url="https://bridge.test/v1", model="custom-model", api_key="sk-sensitive")
        self.assertContains(response, "responses ok")

    def test_create_ai_client_reads_database_settings(self):
        AISettings.objects.create(
            pk=1,
            provider=AIProviderChoices.OPENAI,
            ollama_url="http://127.0.0.1:11434",
            ollama_model="ollama-model",
            openai_base_url="https://api.openai.test/v1",
            openai_model="db-model",
            openai_transcription_model="transcribe-model",
            openai_api_key="db-key",
        )

        client = create_ai_client()

        self.assertIsInstance(client, OpenAIClient)
        self.assertEqual(client.api_key, "db-key")
        self.assertEqual(client.model, "db-model")
        self.assertEqual(client.base_url, "https://api.openai.test/v1")

    def test_check_openai_connection_does_not_leak_key_in_error(self):
        config = AIProviderConfig(
            provider=AIProviderChoices.OPENAI,
            connection_type=AIConnectionTypeChoices.OPENAI_OFFICIAL,
            ollama_url="http://127.0.0.1:11434",
            ollama_model="qwen3.5:9b",
            openai_base_url="https://api.openai.test/v1",
            openai_model="test-model",
            openai_api_style=AIAPIStyleChoices.CHAT_COMPLETIONS,
            openai_transcription_model="transcribe-test",
            openai_api_key="sk-sensitive",
        )

        with patch("ai.config.httpx.get", side_effect=httpx.ConnectError("boom sk-sensitive")):
            result = check_ai_connection(config)

        self.assertFalse(result.ok)
        self.assertNotIn("sk-sensitive", result.message)

    def test_ai_settings_form_shows_current_openai_model_placeholders(self):
        self.client.force_login(self.head)

        response = self.client.get(reverse("ai_settings"))

        self.assertContains(response, 'placeholder="gpt-5.6-sol"')
        self.assertContains(response, 'placeholder="gpt-transcribe"')
        self.assertContains(response, "gpt-5.6-terra")
        self.assertContains(response, "gpt-5.6-luna")
