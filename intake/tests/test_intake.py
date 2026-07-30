from __future__ import annotations

import hashlib
import hmac
import json

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from intake.models import InboundRequest, InboundRequestStatus, ProcessingLog


def signed_headers(body: bytes, *, secret: str = "webhook-secret") -> dict[str, str]:
    timestamp = str(int(timezone.now().timestamp()))
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {"HTTP_X_TIMESTAMP": timestamp, "HTTP_X_SIGNATURE": signature}


@override_settings(WEBHOOK_SECRET="webhook-secret", INTAKE_RATE_LIMIT_IP_PER_HOUR=20, INTAKE_RATE_LIMIT_GLOBAL_PER_MINUTE=60)
class IntakeApiTests(TestCase):
    def payload(self, external_id: str = "lead-1") -> dict:
        return {
            "external_id": external_id,
            "name": "Иван",
            "phone": "+7 999 123-45-67",
            "text": "Интересует Chery Tiggo в кредит",
            "source": "site",
            "received_at": timezone.now().isoformat(),
            "email": "ivan@example.test",
            "extra": {"utm": "test"},
        }

    def post_signed(self, payload: dict):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self.client.post(
            "/api/v1/intake/lead",
            data=body,
            content_type="application/json",
            **signed_headers(body),
        )

    def test_signed_webhook_creates_received_request(self):
        response = self.post_signed(self.payload())
        self.assertEqual(response.status_code, 202)
        inbound = InboundRequest.objects.get()
        self.assertEqual(inbound.status, InboundRequestStatus.RECEIVED)
        self.assertEqual(inbound.ip_address, "127.0.0.1")
        self.assertTrue(inbound.payload_hash)
        self.assertTrue(inbound.processing_logs.filter(step="received").exists())

    def test_bad_signature_returns_401_without_row(self):
        body = json.dumps(self.payload()).encode("utf-8")
        response = self.client.post(
            "/api/v1/intake/lead",
            data=body,
            content_type="application/json",
            HTTP_X_TIMESTAMP=str(int(timezone.now().timestamp())),
            HTTP_X_SIGNATURE="bad-signature",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(InboundRequest.objects.count(), 0)

    def test_duplicate_external_id_creates_duplicate_row(self):
        first = self.post_signed(self.payload("same-id"))
        second = self.post_signed(self.payload("same-id"))
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(InboundRequest.objects.count(), 2)
        duplicate = InboundRequest.objects.get(status=InboundRequestStatus.DUPLICATE)
        self.assertEqual(duplicate.duplicate_of_request_id, first.json()["request_id"])


class IntakeFormTests(TestCase):
    def test_honeypot_creates_blocked_request_with_same_success_response(self):
        response = self.client.post(
            reverse("lead_form"),
            {
                "name": "Bot",
                "phone": "+7 999 000-00-00",
                "email": "",
                "text": "spam",
                "source": "site",
                "website": "filled",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Заявка принята")
        inbound = InboundRequest.objects.get()
        self.assertEqual(inbound.status, InboundRequestStatus.BLOCKED)
        self.assertEqual(inbound.spam_reason, "honeypot")

    @override_settings(INTAKE_RATE_LIMIT_IP_PER_HOUR=0, INTAKE_RATE_LIMIT_GLOBAL_PER_MINUTE=60)
    def test_rate_limit_creates_blocked_request(self):
        response = self.client.post(
            reverse("lead_form"),
            {
                "name": "Иван",
                "phone": "+7 999 000-00-01",
                "email": "",
                "text": "Хочу узнать цену",
                "source": "site",
                "website": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        inbound = InboundRequest.objects.get()
        self.assertEqual(inbound.status, InboundRequestStatus.BLOCKED)
        self.assertIn("ip rate limit", inbound.spam_reason)
