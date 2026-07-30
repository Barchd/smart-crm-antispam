"""Tests for trust_level: external vs internal intake signal policy."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from intake.models import InboundRequest, InboundRequestStatus, TrustLevel
from intake.risk import evaluate_rules
from intake.services import payload_hash

GOOD_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
INTERNAL_IP = "10.0.0.1"


def signed_headers(body: bytes, *, secret: str = "webhook-secret") -> dict[str, str]:
    timestamp = str(int(timezone.now().timestamp()))
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {"HTTP_X_TIMESTAMP": timestamp, "HTTP_X_SIGNATURE": sig}


def _make(
    *,
    external_id: str,
    phone: str = "+7 999 000-00-00",
    phone_normalized: str = "",
    email: str = "lead@example.test",
    text: str = "Хочу купить автомобиль",
    ip: str = INTERNAL_IP,
    user_agent: str = GOOD_UA,
    trust_level: str = TrustLevel.EXTERNAL,
    minutes_ago: int = 0,
) -> InboundRequest:
    p = {"phone": phone, "text": text}
    obj = InboundRequest.objects.create(
        external_id=external_id,
        source_type="api",
        source_name="api",
        name_raw="Lead",
        phone_raw=phone,
        phone_normalized=phone_normalized,
        email_raw=email,
        message_text=text,
        received_at=timezone.now() - timedelta(minutes=minutes_ago),
        raw_payload_json=p,
        payload_hash=payload_hash(p),
        ip_address=ip,
        user_agent=user_agent,
        status=InboundRequestStatus.RECEIVED,
        trust_level=trust_level,
    )
    if minutes_ago:
        InboundRequest.objects.filter(pk=obj.pk).update(
            created_at=timezone.now() - timedelta(minutes=minutes_ago)
        )
        obj.refresh_from_db()
    return obj


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: external signed + 3+ contacts same IP → ip_multi_identity fires
# ──────────────────────────────────────────────────────────────────────────────

class ExternalVelocityTests(TestCase):
    def test_external_ip_multi_identity_fires_for_external_source(self):
        """External requests with 3 distinct phones from same IP → ip_multi_identity."""
        phones = ["+79510000001", "+79510000002", "+79510000003"]
        for i, ph in enumerate(phones):
            _make(
                external_id=f"ext-mi-{i}",
                phone=ph,
                phone_normalized=ph.replace("+", ""),
                ip=INTERNAL_IP,
                trust_level=TrustLevel.EXTERNAL,
                minutes_ago=30,
            )
        subject = _make(
            external_id="ext-mi-subject",
            phone="+79510000099",
            ip=INTERNAL_IP,
            trust_level=TrustLevel.EXTERNAL,
        )
        risk = evaluate_rules(subject)
        self.assertIn("ip_multi_identity", [s.code for s in risk.signals])

    def test_external_ip_flood_fires_for_external_source(self):
        """6 external others from same IP in 1h → ip_flood fires."""
        for i in range(6):
            _make(
                external_id=f"ext-flood-{i}",
                phone=f"+7951111{i:04d}",
                ip=INTERNAL_IP,
                trust_level=TrustLevel.EXTERNAL,
                minutes_ago=20,
            )
        subject = _make(
            external_id="ext-flood-subject",
            phone="+79519999999",
            ip=INTERNAL_IP,
            trust_level=TrustLevel.EXTERNAL,
        )
        risk = evaluate_rules(subject)
        self.assertIn("ip_flood", [s.code for s in risk.signals])


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: internal signed + 10 requests same IP different phones → no velocity signals
# ──────────────────────────────────────────────────────────────────────────────

class InternalNoVelocityTests(TestCase):
    def test_internal_ip_multi_identity_does_not_fire(self):
        """Internal trust: 3+ phones from same IP must NOT trigger ip_multi_identity."""
        phones = ["+79521000001", "+79521000002", "+79521000003"]
        for i, ph in enumerate(phones):
            _make(
                external_id=f"int-mi-{i}",
                phone=ph,
                phone_normalized=ph.replace("+", ""),
                ip=INTERNAL_IP,
                trust_level=TrustLevel.INTERNAL,
                minutes_ago=30,
            )
        subject = _make(
            external_id="int-mi-subject",
            phone="+79521000099",
            ip=INTERNAL_IP,
            trust_level=TrustLevel.INTERNAL,
        )
        risk = evaluate_rules(subject)
        codes = [s.code for s in risk.signals]
        self.assertNotIn("ip_multi_identity", codes)
        self.assertNotIn("ip_flood", codes)

    def test_internal_ip_flood_does_not_fire(self):
        """10 internal requests from same IP in 1h → ip_flood must NOT fire."""
        for i in range(10):
            _make(
                external_id=f"int-flood-{i}",
                phone=f"+7952222{i:04d}",
                ip=INTERNAL_IP,
                trust_level=TrustLevel.INTERNAL,
                minutes_ago=15,
            )
        subject = _make(
            external_id="int-flood-subject",
            phone="+79529999999",
            ip=INTERNAL_IP,
            trust_level=TrustLevel.INTERNAL,
        )
        risk = evaluate_rules(subject)
        codes = [s.code for s in risk.signals]
        self.assertNotIn("ip_flood", codes)
        self.assertNotIn("ip_multi_identity", codes)

    def test_internal_ua_flood_does_not_fire(self):
        """Internal trust: 6+ requests with same UA → ua_flood must NOT fire."""
        for i in range(6):
            _make(
                external_id=f"int-ua-{i}",
                phone=f"+7953333{i:04d}",
                user_agent=GOOD_UA,
                ip=INTERNAL_IP,
                trust_level=TrustLevel.INTERNAL,
                minutes_ago=20,
            )
        subject = _make(
            external_id="int-ua-subject",
            phone="+79539999999",
            user_agent=GOOD_UA,
            ip=INTERNAL_IP,
            trust_level=TrustLevel.INTERNAL,
        )
        risk = evaluate_rules(subject)
        codes = [s.code for s in risk.signals]
        self.assertNotIn("ua_flood", codes)
        self.assertNotIn("ua_multi_identity", codes)

    def test_internal_text_risk_still_fires(self):
        """Internal trust does NOT disable text-based signals (promo, profanity etc.)."""
        subject = _make(
            external_id="int-promo",
            phone="+79534444444",
            text="Казино ставки крипта быстрый доход",
            ip=INTERNAL_IP,
            trust_level=TrustLevel.INTERNAL,
        )
        risk = evaluate_rules(subject)
        self.assertIn("promo_keywords", [s.code for s in risk.signals])

    def test_internal_blocklist_still_fires(self):
        """Phone blocklist check is NOT skipped for internal sources."""
        from intake.models import Blocklist, BlocklistKind
        from crm.phones import normalize_phone

        phone = "+79535555555"
        normalized = normalize_phone(phone)
        Blocklist.objects.create(kind=BlocklistKind.PHONE, value=normalized, reason="test")
        subject = _make(
            external_id="int-blocklist",
            phone=phone,
            phone_normalized=normalized,
            ip=INTERNAL_IP,
            trust_level=TrustLevel.INTERNAL,
        )
        risk = evaluate_rules(subject)
        self.assertTrue(risk.blocklisted)


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: body trust=internal without right header → stays external
# ──────────────────────────────────────────────────────────────────────────────

@override_settings(WEBHOOK_SECRET="webhook-secret", INTAKE_RATE_LIMIT_IP_PER_HOUR=20, INTAKE_RATE_LIMIT_GLOBAL_PER_MINUTE=60)
class TrustHeaderEnforcementTests(TestCase):
    def _post_signed(self, payload: dict, extra_headers: dict | None = None) -> object:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = signed_headers(body)
        if extra_headers:
            headers.update(extra_headers)
        return self.client.post(
            "/api/v1/intake/lead",
            data=body,
            content_type="application/json",
            **headers,
        )

    def test_body_trust_field_ignored_stays_external(self):
        """Passing trust=internal in the JSON body must NOT set internal trust."""
        payload = {
            "external_id": "trust-body-1",
            "name": "Bot",
            "phone": "+7 999 111-11-11",
            "text": "test",
            "source": "api",
            "metadata": {"trust": "internal"},
        }
        response = self._post_signed(payload)
        self.assertEqual(response.status_code, 202)
        inbound = InboundRequest.objects.get(external_id="trust-body-1")
        self.assertEqual(inbound.trust_level, TrustLevel.EXTERNAL)

    def test_internal_header_with_valid_hmac_sets_internal_trust(self):
        """X-Intake-Trust: internal + valid HMAC → trust_level stored as internal."""
        payload = {
            "external_id": "trust-header-1",
            "name": "Server",
            "phone": "+7 999 222-22-22",
            "text": "Automated lead from 1C",
            "source": "crm_import",
        }
        response = self._post_signed(payload, {"HTTP_X_INTAKE_TRUST": "internal"})
        self.assertEqual(response.status_code, 202)
        inbound = InboundRequest.objects.get(external_id="trust-header-1")
        self.assertEqual(inbound.trust_level, TrustLevel.INTERNAL)

    def test_external_header_default_is_external(self):
        """No X-Intake-Trust header → trust_level defaults to external."""
        payload = {
            "external_id": "trust-default-1",
            "name": "Lead",
            "phone": "+7 999 333-33-33",
            "text": "Интересует кредит",
            "source": "site",
        }
        response = self._post_signed(payload)
        self.assertEqual(response.status_code, 202)
        inbound = InboundRequest.objects.get(external_id="trust-default-1")
        self.assertEqual(inbound.trust_level, TrustLevel.EXTERNAL)


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: bad signature + X-Intake-Trust: internal → 401, no row
# ──────────────────────────────────────────────────────────────────────────────

@override_settings(WEBHOOK_SECRET="webhook-secret", INTAKE_RATE_LIMIT_IP_PER_HOUR=20, INTAKE_RATE_LIMIT_GLOBAL_PER_MINUTE=60)
class BadSignatureTrustTests(TestCase):
    def test_bad_signature_with_internal_trust_header_returns_401(self):
        """Bad HMAC + X-Intake-Trust: internal → 401, no InboundRequest created."""
        payload = {
            "external_id": "bad-sig-internal",
            "name": "Attacker",
            "phone": "+7 999 444-44-44",
            "text": "Trying to escalate trust",
            "source": "hack",
        }
        body = json.dumps(payload).encode("utf-8")
        response = self.client.post(
            "/api/v1/intake/lead",
            data=body,
            content_type="application/json",
            HTTP_X_TIMESTAMP=str(int(timezone.now().timestamp())),
            HTTP_X_SIGNATURE="invalid-signature",
            HTTP_X_INTAKE_TRUST="internal",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(InboundRequest.objects.count(), 0)


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: Telegram path is not broken (trust=internal set automatically)
# ──────────────────────────────────────────────────────────────────────────────

class TelegramTrustTests(TestCase):
    def test_telegram_create_sets_internal_trust(self):
        """create_telegram_inbound_request must set trust_level=internal."""
        from bot.customer import build_lead_from_message, create_telegram_inbound_request
        from types import SimpleNamespace

        message = SimpleNamespace(
            from_user=SimpleNamespace(id=42, username="user42", language_code="ru"),
            chat=SimpleNamespace(id=42),
            message_id=1,
        )
        lead = build_lead_from_message(message, name="Иван", phone="+79991234567", question="Хочу Haval")
        inbound = create_telegram_inbound_request(lead)

        self.assertEqual(inbound.trust_level, TrustLevel.INTERNAL)
        self.assertEqual(inbound.source_type, "telegram")

    def test_telegram_ua_flood_does_not_fire(self):
        """Many Telegram requests (all user_agent='telegram-bot') must NOT trigger ua_flood."""
        for i in range(7):
            _make(
                external_id=f"tg-ua-{i}",
                phone=f"+7954{i:07d}",
                user_agent="telegram-bot",
                ip=None,
                trust_level=TrustLevel.INTERNAL,
                minutes_ago=10,
            )
        subject = _make(
            external_id="tg-ua-subject",
            phone="+79549999999",
            user_agent="telegram-bot",
            ip=None,
            trust_level=TrustLevel.INTERNAL,
        )
        risk = evaluate_rules(subject)
        self.assertNotIn("ua_flood", [s.code for s in risk.signals])
