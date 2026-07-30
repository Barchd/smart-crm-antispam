"""Tests for WebhookSettings model and /settings/webhook/ view."""

from __future__ import annotations

import hashlib
import hmac
import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from crm.models import RoleChoices
from intake.models import WebhookSettings
from intake.webhook_config import get_webhook_secret


def signed_headers(body: bytes, *, secret: str) -> dict[str, str]:
    ts = str(int(timezone.now().timestamp()))
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"HTTP_X_TIMESTAMP": ts, "HTTP_X_SIGNATURE": sig}


class WebhookSettingsModelTests(TestCase):
    def test_current_seeds_from_env_on_first_call(self):
        with self.settings(WEBHOOK_SECRET="env-secret-xyz"):
            ws = WebhookSettings.current()
        self.assertEqual(ws.webhook_secret, "env-secret-xyz")

    def test_get_webhook_secret_returns_db_value_over_env(self):
        WebhookSettings.objects.update_or_create(pk=1, defaults={"webhook_secret": "db-secret-abc"})
        with self.settings(WEBHOOK_SECRET="env-secret-xyz"):
            self.assertEqual(get_webhook_secret(), "db-secret-abc")

    def test_get_webhook_secret_falls_back_to_env_when_db_empty(self):
        WebhookSettings.objects.update_or_create(pk=1, defaults={"webhook_secret": ""})
        with self.settings(WEBHOOK_SECRET="env-fallback"):
            self.assertEqual(get_webhook_secret(), "env-fallback")


@override_settings(WEBHOOK_SECRET="webhook-secret", INTAKE_RATE_LIMIT_IP_PER_HOUR=20, INTAKE_RATE_LIMIT_GLOBAL_PER_MINUTE=60)
class WebhookSignatureWithDbSecretTests(TestCase):
    """Verify that signature_valid uses the DB secret when one is set."""

    def _payload(self, eid: str = "ws-1") -> dict:
        return {"external_id": eid, "name": "Test", "phone": "+7 999 111-11-11",
                "text": "Хочу автомобиль", "source": "site"}

    def _post(self, payload: dict, secret: str, extra: dict | None = None) -> object:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        headers = signed_headers(body, secret=secret)
        if extra:
            headers.update(extra)
        return self.client.post(
            "/api/v1/intake/lead", data=body,
            content_type="application/json", **headers,
        )

    def test_db_secret_overrides_env_for_signature(self):
        """After saving a new DB secret, only that secret is accepted."""
        WebhookSettings.objects.update_or_create(pk=1, defaults={"webhook_secret": "new-db-secret"})
        # Env secret no longer valid
        resp_env = self._post(self._payload("ws-env"), secret="webhook-secret")
        self.assertEqual(resp_env.status_code, 401)
        # DB secret works
        resp_db = self._post(self._payload("ws-db"), secret="new-db-secret")
        self.assertEqual(resp_db.status_code, 202)

    def test_env_secret_works_when_db_row_empty(self):
        WebhookSettings.objects.update_or_create(pk=1, defaults={"webhook_secret": ""})
        resp = self._post(self._payload("ws-env-only"), secret="webhook-secret")
        self.assertEqual(resp.status_code, 202)


class WebhookSettingsViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.head = user_model.objects.create_user(
            username="head", password="secret", full_name="Head", role=RoleChoices.HEAD
        )
        self.manager = user_model.objects.create_user(
            username="manager", password="secret", full_name="Manager", role=RoleChoices.MANAGER
        )

    def test_manager_cannot_access_webhook_settings(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("webhook_settings"))
        self.assertEqual(response.status_code, 403)

    def test_head_can_view_webhook_settings(self):
        self.client.force_login(self.head)
        response = self.client.get(reverse("webhook_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Webhook intake")
        self.assertContains(response, "Сгенерировать новый секрет")

    def test_generate_creates_new_secret_and_shows_it_once(self):
        self.client.force_login(self.head)
        response = self.client.post(
            reverse("webhook_settings"), {"action": "generate"}, follow=False
        )
        self.assertEqual(response.status_code, 200)
        ws = WebhookSettings.objects.get(pk=1)
        self.assertTrue(ws.has_secret)
        self.assertEqual(ws.updated_by, self.head)
        # New secret shown in response body
        self.assertContains(response, ws.webhook_secret)

    def test_generate_secret_not_visible_on_normal_get(self):
        """After redirect/GET the full secret is not shown — only the mask."""
        self.client.force_login(self.head)
        self.client.post(reverse("webhook_settings"), {"action": "generate"})
        ws = WebhookSettings.objects.get(pk=1)
        get_resp = self.client.get(reverse("webhook_settings"))
        self.assertNotContains(get_resp, ws.webhook_secret)
        # Mask shown
        self.assertContains(get_resp, "***")

    def test_secret_not_in_html_on_get(self):
        """Even if DB has a secret, GET must not reveal it — only mask."""
        WebhookSettings.objects.update_or_create(
            pk=1, defaults={"webhook_secret": "super-secret-value-12345", "updated_by": self.head}
        )
        self.client.force_login(self.head)
        response = self.client.get(reverse("webhook_settings"))
        self.assertNotContains(response, "super-secret-value-12345")
        self.assertContains(response, "2345")  # tail of mask

    def test_csrf_required_for_generate(self):
        """POST without CSRF must be rejected (enforced by Django middleware)."""
        self.client.force_login(self.head)
        # Django test client enforces CSRF by default when enforce_csrf_checks=True
        from django.test import Client
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.head)
        response = csrf_client.post(reverse("webhook_settings"), {"action": "generate"})
        self.assertEqual(response.status_code, 403)
