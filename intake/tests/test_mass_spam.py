from __future__ import annotations

import hashlib
import hmac
import json
import random
import string

from django.test import TestCase, override_settings
from django.utils import timezone

from intake.models import InboundRequest, InboundRequestStatus, ProcessingLog
from intake.services import process_request_by_rules


def signed_headers(body: bytes, *, secret: str = "webhook-secret") -> dict[str, str]:
    timestamp = str(int(timezone.now().timestamp()))
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {
        "HTTP_X_TIMESTAMP": timestamp,
        "HTTP_X_SIGNATURE": signature,
        "HTTP_X_FORWARDED_FOR": "203.0.113.10",
        "HTTP_USER_AGENT": "mass-spam-test/1.0",
    }


@override_settings(WEBHOOK_SECRET="webhook-secret", INTAKE_RATE_LIMIT_IP_PER_HOUR=12, INTAKE_RATE_LIMIT_GLOBAL_PER_MINUTE=1000)
class MassSpamTests(TestCase):
    def spam_payload(self, rng: random.Random, index: int) -> dict:
        suffix = "".join(rng.choices(string.ascii_lowercase + string.digits, k=10))
        return {
            "external_id": f"mass-spam-{index}-{suffix}",
            "name": f"Spam {suffix}",
            "phone": f"+7 999 {800 + index:03d}-{index % 100:02d}-{(index * 7) % 100:02d}",
            "email": f"{suffix}@mailinator.com",
            "text": f"казино crypto {suffix} http://spam.example/{suffix} http://spam.example/{index}",
            "source": "ads",
            "received_at": timezone.now().isoformat(),
            "metadata": {"campaign": "mass-spam-test", "random_suffix": suffix},
        }

    def post_signed(self, payload: dict):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self.client.post(
            "/api/v1/intake/lead",
            data=body,
            content_type="application/json",
            **signed_headers(body),
        )

    def test_mass_random_spam_is_stored_limited_and_never_creates_deals(self):
        rng = random.Random(42)

        responses = [self.post_signed(self.spam_payload(rng, index)) for index in range(25)]

        self.assertTrue(all(response.status_code in {200, 202} for response in responses))
        self.assertEqual(InboundRequest.objects.count(), 25)
        self.assertEqual(InboundRequest.objects.filter(status=InboundRequestStatus.RECEIVED).count(), 12)
        self.assertEqual(InboundRequest.objects.filter(status=InboundRequestStatus.BLOCKED).count(), 13)
        self.assertEqual(InboundRequest.objects.filter(status=InboundRequestStatus.DUPLICATE).count(), 0)

        for inbound in InboundRequest.objects.filter(status=InboundRequestStatus.RECEIVED):
            process_request_by_rules(inbound=inbound)

        self.assertEqual(InboundRequest.objects.exclude(status=InboundRequestStatus.BLOCKED).count(), 0)
        self.assertEqual(InboundRequest.objects.filter(linked_deal__isnull=False).count(), 0)
        self.assertEqual(ProcessingLog.objects.filter(step="received").count(), 25)
        self.assertGreaterEqual(ProcessingLog.objects.filter(step__in=["blocklist_checked", "rules_risk_scored"]).count(), 12)

