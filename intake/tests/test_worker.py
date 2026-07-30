from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from ai.schemas import AIAnalysis
from crm.models import RoleChoices
from intake.models import InboundRequest, InboundRequestStatus
from intake.services import payload_hash
from intake.worker import process_next_request, reset_stale_processing


class FakeAIClient:
    def analyze(self, *, inbound):
        return AIAnalysis(
            topic="покупка автомобиля",
            need="подобрать автомобиль",
            urgency="medium",
            category="purchase",
            spam_probability=0.05,
            toxicity=0.0,
            troll_probability=0.0,
            off_topic_probability=0.0,
            moderation_labels=[],
            department="sales",
            suggested_employee_id=None,
            summary="Клиент хочет подобрать автомобиль.",
            suggested_reply="Здравствуйте! Уточните модель и бюджет.",
        )


class WorkerTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.manager = user_model.objects.create_user(username="manager", password="secret", full_name="Manager", role=RoleChoices.MANAGER)

    def inbound(self, *, external_id="worker-1", phone="+7 999 500-00-00", status=InboundRequestStatus.RECEIVED, payload=None) -> InboundRequest:
        payload = payload or {"phone": phone, "text": "Хочу купить автомобиль"}
        return InboundRequest.objects.create(
            external_id=external_id,
            source_type="site",
            source_name="site",
            name_raw="Lead",
            phone_raw=phone,
            email_raw="lead@example.test",
            message_text=str(payload.get("text") or "Хочу купить автомобиль"),
            raw_payload_json=payload,
            payload_hash=payload_hash(payload),
            ip_address="127.0.0.1",
            status=status,
        )

    def test_worker_processes_received_request(self):
        inbound = self.inbound()

        result = process_next_request(ai_client=FakeAIClient())

        inbound.refresh_from_db()
        self.assertTrue(result.processed)
        self.assertEqual(inbound.status, InboundRequestStatus.PROCESSED)
        self.assertIsNone(inbound.locked_at)
        self.assertIsNotNone(inbound.linked_deal)

    @override_settings(DEBUG=True)
    def test_force_error_retries_then_fails(self):
        inbound = self.inbound(payload={"phone": "+7 999 501-00-00", "text": "Хочу купить автомобиль", "force_error": True})

        for attempt in range(5):
            result = process_next_request(ai_client=FakeAIClient())
            inbound.refresh_from_db()
            self.assertTrue(result.processed)
            if attempt < 4:
                self.assertEqual(inbound.status, InboundRequestStatus.RETRY_WAIT)
                inbound.next_retry_at = timezone.now() - timedelta(seconds=1)
                inbound.save(update_fields=["next_retry_at"])

        inbound.refresh_from_db()
        self.assertEqual(inbound.status, InboundRequestStatus.FAILED)
        self.assertIsNone(inbound.locked_at)
        self.assertIsNone(inbound.linked_deal)

    def test_stale_processing_is_released(self):
        inbound = self.inbound(status=InboundRequestStatus.PROCESSING)
        inbound.locked_at = timezone.now() - timedelta(minutes=10)
        inbound.save(update_fields=["locked_at"])

        released = reset_stale_processing()

        inbound.refresh_from_db()
        self.assertEqual(released, 1)
        self.assertEqual(inbound.status, InboundRequestStatus.RETRY_WAIT)
        self.assertIsNone(inbound.locked_at)

    def test_worker_ignores_duplicate_and_blocked(self):
        self.inbound(external_id="blocked", status=InboundRequestStatus.BLOCKED)
        self.inbound(external_id="duplicate", status=InboundRequestStatus.DUPLICATE)

        result = process_next_request(ai_client=FakeAIClient())

        self.assertFalse(result.processed)
        self.assertEqual(result.status, "idle")
