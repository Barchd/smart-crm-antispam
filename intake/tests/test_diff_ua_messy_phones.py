"""Spam with different User-Agents and messy RU phone formats (demo_spam_attack)."""

from __future__ import annotations

import hashlib
import hmac
import json
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from intake.management.commands.demo_spam_attack import (
    INVALID_PHONE_IP,
    MESSY_PHONES,
    REAL_USER_AGENTS,
)
from intake.models import InboundRequest, InboundRequestStatus
from intake.risk import evaluate_rules
from intake.services import process_request_by_rules
from intake.tests.test_fingerprint_spam import _make


def signed_headers(
    body: bytes,
    *,
    secret: str = "webhook-secret",
    user_agent: str,
    ip: str = INVALID_PHONE_IP,
) -> dict[str, str]:
    timestamp = str(int(timezone.now().timestamp()))
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {
        "HTTP_X_TIMESTAMP": timestamp,
        "HTTP_X_SIGNATURE": signature,
        "HTTP_X_FORWARDED_FOR": ip,
        "HTTP_USER_AGENT": user_agent,
    }


class MessyPhoneFormatTests(TestCase):
    def test_each_messy_phone_gives_phone_invalid(self):
        for index, phone in enumerate(MESSY_PHONES):
            with self.subTest(phone=phone):
                inbound = _make(
                    external_id=f"messy-phone-{index}",
                    phone=phone,
                    user_agent=REAL_USER_AGENTS[index % len(REAL_USER_AGENTS)],
                    ip=INVALID_PHONE_IP,
                    email=f"spam{index}@mail.ru",
                )
                risk = evaluate_rules(inbound)
                codes = [s.code for s in risk.signals]
                self.assertIn("phone_invalid", codes)
                self.assertFalse(risk.phone_valid)
                self.assertEqual(risk.phone_normalized, "")


@override_settings(
    WEBHOOK_SECRET="webhook-secret",
    INTAKE_RATE_LIMIT_IP_PER_HOUR=100,
    INTAKE_RATE_LIMIT_GLOBAL_PER_MINUTE=1000,
    ALLOWED_HOSTS=["127.0.0.1", "testserver"],
)
class DiffUaMessyPhoneSpamTests(TestCase):
    """Разные UA + кривые телефоны с одного IP → webhook принимает, rules блокирует."""

    def post_spam(self, *, index: int, phone: str, user_agent: str):
        payload = {
            "external_id": f"diff-ua-messy-{index}",
            "source": "site_form",
            "name": f"Spam Lead {index}",
            "phone": phone,
            "email": f"lead{index}@yandex.ru",
            "text": "Интересует авто в кредит, перезвоните",
            "received_at": timezone.now().isoformat(),
            "metadata": {"campaign": "diff-ua-messy-phones", "index": index},
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self.client.post(
            "/api/v1/intake/lead",
            data=body,
            content_type="application/json",
            **signed_headers(body, user_agent=user_agent, ip=INVALID_PHONE_IP),
        )

    def test_spam_wave_different_ua_and_messy_phones_blocked_without_deals(self):
        phones = list(MESSY_PHONES)
        self.assertGreaterEqual(len(phones), 8)
        self.assertGreaterEqual(len(REAL_USER_AGENTS), 6)

        responses = []
        for index, phone in enumerate(phones):
            ua = REAL_USER_AGENTS[index % len(REAL_USER_AGENTS)]
            responses.append(self.post_spam(index=index, phone=phone, user_agent=ua))

        self.assertTrue(all(r.status_code in {200, 202} for r in responses))
        self.assertEqual(InboundRequest.objects.count(), len(phones))

        user_agents = set(InboundRequest.objects.values_list("user_agent", flat=True))
        self.assertGreaterEqual(len(user_agents), 6)

        raw_phones = list(InboundRequest.objects.values_list("phone_raw", flat=True))
        self.assertEqual(set(raw_phones), set(phones))
        self.assertTrue(
            all(ip == INVALID_PHONE_IP for ip in InboundRequest.objects.values_list("ip_address", flat=True))
        )

        for inbound in InboundRequest.objects.all():
            process_request_by_rules(inbound=inbound)
            inbound.refresh_from_db()
            self.assertEqual(inbound.status, InboundRequestStatus.BLOCKED)
            self.assertIn("телефон", (inbound.last_error or "").casefold())
            self.assertFalse(inbound.linked_deal_id)

        self.assertEqual(InboundRequest.objects.filter(linked_deal__isnull=False).count(), 0)
        self.assertEqual(
            InboundRequest.objects.filter(status=InboundRequestStatus.BLOCKED).count(),
            len(phones),
        )

    def test_demo_spam_attack_invalid_phone_scenario(self):
        out = StringIO()
        call_command(
            "demo_spam_attack",
            scenario="invalid-phone",
            count=5,
            delay=0,
            process=True,
            rules_only=True,
            tag="testmessy",
            stdout=out,
        )
        text = out.getvalue()
        self.assertIn("invalid-phone", text)
        self.assertIn("8985451833", text)

        qs = InboundRequest.objects.filter(external_id__startswith="defense-spam-testmessy-bad-")
        self.assertEqual(qs.count(), 5)
        self.assertEqual(qs.filter(status=InboundRequestStatus.BLOCKED).count(), 5)
        self.assertTrue(all(str(ip) == INVALID_PHONE_IP for ip in qs.values_list("ip_address", flat=True)))
        self.assertGreaterEqual(qs.values("user_agent").distinct().count(), 4)
        self.assertEqual(qs.filter(linked_deal__isnull=False).count(), 0)
