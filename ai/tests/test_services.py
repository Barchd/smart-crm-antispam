from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from ai.client import AIModelUnavailable
from ai.schemas import AIAnalysis
from ai.services import process_request_with_ai
from channels.models import Dialog
from crm.models import Deal, RoleChoices
from intake.models import InboundRequest, InboundRequestStatus, ProcessingLog
from intake.services import payload_hash


class FakeAIClient:
    def __init__(self, analysis: AIAnalysis | None = None, error: Exception | None = None):
        self.analysis = analysis
        self.error = error
        self.called = False

    def analyze(self, *, inbound):
        self.called = True
        if self.error:
            raise self.error
        return self.analysis


def valid_analysis(**overrides) -> AIAnalysis:
    data = {
        "topic": "покупка автомобиля",
        "need": "подобрать автомобиль",
        "urgency": "medium",
        "category": "purchase",
        "spam_probability": 0.05,
        "toxicity": 0.0,
        "troll_probability": 0.0,
        "off_topic_probability": 0.0,
        "moderation_labels": [],
        "department": "sales",
        "suggested_employee_id": None,
        "summary": "Клиент хочет подобрать автомобиль.",
        "suggested_reply": "Здравствуйте! Уточните желаемую модель и бюджет.",
    }
    data.update(overrides)
    return AIAnalysis(**data)


class AIProcessingTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.manager = user_model.objects.create_user(username="manager", password="secret", full_name="Manager", role=RoleChoices.MANAGER)

    def inbound(self, *, external_id="ai-1", phone="+7 999 100-00-00", text="Хочу купить автомобиль", payload=None) -> InboundRequest:
        payload = payload or {"phone": phone, "text": text}
        return InboundRequest.objects.create(
            external_id=external_id,
            source_type="site",
            source_name="site",
            name_raw="Lead",
            phone_raw=phone,
            email_raw="lead@example.test",
            message_text=text,
            raw_payload_json=payload,
            payload_hash=payload_hash(payload),
            ip_address="127.0.0.1",
            status=InboundRequestStatus.RECEIVED,
        )

    def test_ai_error_moves_request_to_retry_wait_without_exception(self):
        inbound = self.inbound()

        process_request_with_ai(inbound=inbound, client=FakeAIClient(error=AIModelUnavailable("invalid urgency")))

        inbound.refresh_from_db()
        self.assertEqual(inbound.status, InboundRequestStatus.RETRY_WAIT)
        self.assertEqual(inbound.retry_count, 1)
        self.assertIsNone(inbound.linked_deal)

    def test_ai_cannot_lower_rules_risk(self):
        payload = {"phone": "+7 999 200-00-00", "text": "http://a.test http://b.test"}
        self.inbound(external_id="first", phone="+7 999 200-00-00", text="first normal text", payload=payload)
        inbound = self.inbound(external_id="second", phone="+7 999 200-00-00", text="http://a.test http://b.test", payload=payload)

        process_request_with_ai(inbound=inbound, client=FakeAIClient(valid_analysis(spam_probability=0.0)))

        inbound.refresh_from_db()
        self.assertEqual(inbound.status, InboundRequestStatus.SUSPICIOUS)
        self.assertGreaterEqual(inbound.risk_score_final, inbound.risk_score_rules)
        self.assertIsNone(inbound.linked_deal)

    def test_invalid_phone_in_ai_log_includes_raw_phone_details(self):
        inbound = self.inbound(phone="abc", text="Хочу купить автомобиль")

        process_request_with_ai(inbound=inbound, client=FakeAIClient(valid_analysis()))

        inbound.refresh_from_db()
        log = inbound.processing_logs.get(step="business_validation_failed")
        self.assertEqual(inbound.status, InboundRequestStatus.BLOCKED)
        self.assertIn("abc", log.message)
        self.assertEqual(log.details_json["error"], "Телефон не разбирается")
        self.assertEqual(log.details_json["phone_raw"], "abc")
        self.assertEqual(log.details_json["email_raw"], "lead@example.test")

    def test_ai_toxicity_can_make_request_suspicious_without_deal(self):
        inbound = self.inbound(text="Вы ужасные идиоты, просто хотел потроллить")

        process_request_with_ai(
            inbound=inbound,
            client=FakeAIClient(valid_analysis(toxicity=0.72, moderation_labels=["toxicity", "troll"])),
        )

        inbound.refresh_from_db()
        self.assertEqual(inbound.status, InboundRequestStatus.SUSPICIOUS)
        self.assertIsNone(inbound.linked_deal)
        self.assertEqual(inbound.ai_toxicity, 0.72)
        self.assertEqual(inbound.ai_moderation_labels, ["toxicity", "troll"])
        self.assertGreaterEqual(inbound.risk_score_final, 72)
        self.assertIn("AI: toxicity", inbound.spam_reason)

    def test_ai_off_topic_can_make_request_suspicious_without_deal(self):
        inbound = self.inbound(text="Хочу заказать пиццу и роллы")

        process_request_with_ai(
            inbound=inbound,
            client=FakeAIClient(valid_analysis(off_topic_probability=0.8, moderation_labels=["off_topic"])),
        )

        inbound.refresh_from_db()
        self.assertEqual(inbound.status, InboundRequestStatus.SUSPICIOUS)
        self.assertIsNone(inbound.linked_deal)
        self.assertEqual(inbound.ai_off_topic_probability, 0.8)
        self.assertGreaterEqual(inbound.risk_score_final, 80)
        self.assertIn("AI: off_topic", inbound.spam_reason)

    def test_explicit_ai_spam_goes_directly_to_blocked(self):
        inbound = self.inbound(text="Смотрите предложение")

        process_request_with_ai(
            inbound=inbound,
            client=FakeAIClient(valid_analysis(category="spam", spam_probability=0.2, moderation_labels=["spam"])),
        )

        inbound.refresh_from_db()
        self.assertEqual(inbound.status, InboundRequestStatus.BLOCKED)
        self.assertIsNone(inbound.linked_deal)
        self.assertIn("AI category: spam", inbound.spam_reason)
        self.assertTrue(inbound.processing_logs.filter(step="ai_blocked", message="explicit spam").exists())

    def test_explicit_spam_hides_existing_deal_immediately(self):
        inbound = self.inbound(text="Хочу купить автомобиль")
        process_request_with_ai(inbound=inbound, client=FakeAIClient(valid_analysis()))
        inbound.refresh_from_db()
        deal = inbound.linked_deal

        process_request_with_ai(
            inbound=inbound,
            client=FakeAIClient(valid_analysis(category="spam", spam_probability=0.2, moderation_labels=["spam"])),
        )

        inbound.refresh_from_db()
        deal.refresh_from_db()
        self.assertEqual(inbound.status, InboundRequestStatus.BLOCKED)
        self.assertTrue(deal.is_spam)
        self.assertEqual(Deal.objects.visible_to(self.manager).count(), 0)

    def test_invalid_phone_in_ai_path_hides_existing_deal(self):
        """AI path: invalid phone must call hide_deal_as_spam_for_request, matching rules path."""
        inbound = self.inbound(phone="+7 999 400-00-00", text="Хочу купить автомобиль")
        # First pass creates a deal via rules
        from intake.services import process_request_by_rules
        process_request_by_rules(inbound=inbound)
        inbound.refresh_from_db()
        deal = inbound.linked_deal
        self.assertIsNotNone(deal)
        self.assertFalse(deal.is_spam)

        # Simulate a follow-up that now has a garbage phone
        inbound.phone_raw = "garbage"
        inbound.status = InboundRequestStatus.RECEIVED
        inbound.save(update_fields=["phone_raw", "status"])

        process_request_with_ai(inbound=inbound, client=FakeAIClient(valid_analysis()))

        inbound.refresh_from_db()
        deal.refresh_from_db()
        self.assertEqual(inbound.status, InboundRequestStatus.BLOCKED)
        self.assertTrue(deal.is_spam)
        self.assertEqual(Deal.objects.visible_to(self.manager).count(), 0)

    def test_invalid_suggested_employee_id_is_ignored(self):
        inbound = self.inbound(phone="+7 999 300-00-00")

        process_request_with_ai(inbound=inbound, client=FakeAIClient(valid_analysis(suggested_employee_id=999999)))

        inbound.refresh_from_db()
        self.assertEqual(inbound.status, InboundRequestStatus.PROCESSED)
        self.assertIsNone(inbound.ai_suggested_employee)
        self.assertEqual(inbound.linked_deal.reply_draft, "Здравствуйте! Уточните желаемую модель и бюджет.")

    def test_ai_topic_becomes_deal_title(self):
        inbound = self.inbound(
            external_id="telegram-topic",
            phone="+7 999 301-00-00",
            text="Подскажите, есть ли Chery Tiggo в кредит?",
            payload={"phone": "+7 999 301-00-00", "text": "Подскажите, есть ли Chery Tiggo в кредит?", "source": "telegram"},
        )
        inbound.source_type = "telegram"
        inbound.source_name = "telegram bot"
        inbound.save(update_fields=["source_type", "source_name"])

        process_request_with_ai(inbound=inbound, client=FakeAIClient(valid_analysis(topic="кредит на Chery Tiggo")))

        inbound.refresh_from_db()
        self.assertEqual(inbound.status, InboundRequestStatus.PROCESSED)
        self.assertEqual(inbound.linked_deal.title, "кредит на Chery Tiggo")

    def test_technical_ai_topic_does_not_become_telegram_deal_title(self):
        inbound = self.inbound(
            external_id="telegram-technical-topic",
            phone="+7 999 302-00-00",
            text="Подскажите, есть ли Haval Jolion в кредит?",
            payload={"phone": "+7 999 302-00-00", "text": "Подскажите, есть ли Haval Jolion в кредит?", "source": "telegram"},
        )
        inbound.source_type = "telegram"
        inbound.source_name = "Telegram"
        inbound.save(update_fields=["source_type", "source_name"])

        process_request_with_ai(
            inbound=inbound,
            client=FakeAIClient(
                valid_analysis(
                    topic="Заявка Telegram",
                    need="кредит на Haval Jolion",
                    summary="Клиент интересуется Haval Jolion в кредит.",
                )
            ),
        )

        inbound.refresh_from_db()
        self.assertEqual(inbound.status, InboundRequestStatus.PROCESSED)
        self.assertEqual(inbound.ai_topic, "кредит на Haval Jolion")
        self.assertEqual(inbound.linked_deal.title, "кредит на Haval Jolion")
        self.assertNotEqual(inbound.linked_deal.title, "Заявка Telegram")

    def test_reprocess_reuses_linked_open_deal_when_dialog_is_missing(self):
        inbound = self.inbound(
            external_id="telegram-linked-deal",
            phone="+7 999 303-00-00",
            text="Нужен Haval Jolion в кредит",
            payload={"phone": "+7 999 303-00-00", "text": "Нужен Haval Jolion в кредит", "user_id": "777"},
        )
        inbound.source_type = "telegram"
        inbound.source_name = "Telegram"
        inbound.save(update_fields=["source_type", "source_name"])
        process_request_with_ai(inbound=inbound, client=FakeAIClient(valid_analysis(topic="кредит на Haval Jolion")))
        inbound.refresh_from_db()
        original_deal_id = inbound.linked_deal_id
        Dialog.objects.filter(deal_id=original_deal_id).delete()

        process_request_with_ai(
            inbound=inbound,
            client=FakeAIClient(valid_analysis(topic="условия кредита на Haval Jolion")),
        )

        inbound.refresh_from_db()
        inbound.linked_deal.refresh_from_db()
        self.assertEqual(inbound.linked_deal_id, original_deal_id)
        self.assertEqual(Deal.objects.count(), 1)
        self.assertEqual(Dialog.objects.filter(deal_id=original_deal_id).count(), 1)
        self.assertEqual(inbound.linked_deal.title, "условия кредита на Haval Jolion")
        self.assertTrue(inbound.processing_logs.filter(step="deal_reused", message=str(original_deal_id)).exists())

    def test_third_ai_error_creates_fallback_deal(self):
        inbound = self.inbound(phone="+7 999 400-00-00")
        inbound.retry_count = 2
        inbound.save(update_fields=["retry_count"])

        process_request_with_ai(inbound=inbound, client=FakeAIClient(error=AIModelUnavailable("ollama down")))

        inbound.refresh_from_db()
        self.assertEqual(inbound.status, InboundRequestStatus.PROCESSED)
        self.assertIsNotNone(inbound.linked_deal)
        self.assertTrue(inbound.linked_deal.created_without_ai)

    @override_settings(AI_BACKPRESSURE_ENABLED=True, AI_QUEUE_BACKPRESSURE_THRESHOLD=1, AI_RETRY_BACKPRESSURE_THRESHOLD=100)
    def test_queue_backpressure_skips_model_and_creates_fallback_deal(self):
        inbound = self.inbound(phone="+7 999 500-00-00")
        client = FakeAIClient(valid_analysis())

        process_request_with_ai(inbound=inbound, client=client)

        inbound.refresh_from_db()
        self.assertFalse(client.called)
        self.assertEqual(inbound.status, InboundRequestStatus.PROCESSED)
        self.assertTrue(inbound.linked_deal.created_without_ai)
        self.assertTrue(inbound.processing_logs.filter(step="ai_backpressure_fallback").exists())

    @override_settings(AI_BACKPRESSURE_ENABLED=True, AI_QUEUE_BACKPRESSURE_THRESHOLD=100, AI_RETRY_BACKPRESSURE_THRESHOLD=1)
    def test_retry_backpressure_skips_model_and_creates_fallback_deal(self):
        previous = self.inbound(external_id="previous", phone="+7 999 510-00-00")
        ProcessingLog.objects.create(inbound_request=previous, step="ai_retry_wait", status=InboundRequestStatus.RETRY_WAIT)
        inbound = self.inbound(external_id="current", phone="+7 999 510-00-01")
        client = FakeAIClient(valid_analysis())

        process_request_with_ai(inbound=inbound, client=client)

        inbound.refresh_from_db()
        self.assertFalse(client.called)
        self.assertEqual(inbound.status, InboundRequestStatus.PROCESSED)
        self.assertTrue(inbound.linked_deal.created_without_ai)

    @override_settings(AI_BACKPRESSURE_ENABLED=True, AI_QUEUE_BACKPRESSURE_THRESHOLD=1, AI_RETRY_BACKPRESSURE_THRESHOLD=100)
    def test_backpressure_keeps_rules_suspicious_without_deal(self):
        payload = {"phone": "+7 999 520-00-00", "text": "http://a.test http://b.test"}
        self.inbound(external_id="same-payload", phone="+7 999 520-00-00", text="first normal text", payload=payload)
        inbound = self.inbound(external_id="suspicious", phone="+7 999 520-00-00", text="http://a.test http://b.test", payload=payload)
        client = FakeAIClient(valid_analysis(spam_probability=0.0))

        process_request_with_ai(inbound=inbound, client=client)

        inbound.refresh_from_db()
        self.assertFalse(client.called)
        self.assertEqual(inbound.status, InboundRequestStatus.SUSPICIOUS)
        self.assertIsNone(inbound.linked_deal)
        self.assertTrue(inbound.processing_logs.filter(step="ai_backpressure_suspicious").exists())


class FingerprintClusterPromptTests(TestCase):
    """P1: build_messages includes fingerprint_cluster when related requests exist."""

    def _make_inbound(self, external_id, phone, ip="10.180.0.1"):
        from intake.services import payload_hash
        payload = {"phone": phone, "text": "Хочу купить автомобиль"}
        return InboundRequest.objects.create(
            external_id=external_id,
            source_type="site",
            source_name="site",
            name_raw="Lead",
            phone_raw=phone,
            email_raw=f"lead_{external_id}@example.test",
            message_text="Хочу купить автомобиль",
            raw_payload_json=payload,
            payload_hash=payload_hash(payload),
            ip_address=ip,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            status=InboundRequestStatus.RECEIVED,
        )

    def test_build_messages_includes_fingerprint_cluster_when_peers_exist(self):
        """When 2+ related requests share same IP, fingerprint_cluster appears in data."""
        from ai.prompt import build_messages
        import json

        ip = "10.180.0.1"
        self._make_inbound("cluster-peer-1", "+7 928 000-00-01", ip=ip)
        self._make_inbound("cluster-peer-2", "+7 928 000-00-02", ip=ip)
        subject = self._make_inbound("cluster-subject", "+7 928 000-00-03", ip=ip)

        messages = build_messages(inbound=subject)
        user_content = messages[1]["content"]
        data = json.loads(user_content.split("\n", 1)[1])

        cluster = data.get("fingerprint_cluster")
        self.assertIsNotNone(cluster, "fingerprint_cluster must be present in build_messages data")
        self.assertGreaterEqual(cluster["cluster_count"], 2)
        self.assertIn("unique_phones", cluster)
        self.assertIn("unique_emails", cluster)
        self.assertIn("sample_texts", cluster)

    def test_build_messages_no_cluster_for_lone_request(self):
        """Single request with no peers → fingerprint_cluster is None."""
        from ai.prompt import build_messages
        import json

        subject = self._make_inbound("lone-cluster", "+7 929 000-00-00", ip="10.181.0.1")

        messages = build_messages(inbound=subject)
        data = json.loads(messages[1]["content"].split("\n", 1)[1])

        self.assertIsNone(data.get("fingerprint_cluster"))

    def test_build_messages_no_cluster_for_internal_trust(self):
        """Internal trust request → fingerprint_cluster is None (no fingerprint spam context)."""
        from ai.prompt import build_messages
        from intake.models import TrustLevel
        import json

        ip = "10.182.0.1"
        self._make_inbound("int-peer-1", "+7 930 000-00-01", ip=ip)
        self._make_inbound("int-peer-2", "+7 930 000-00-02", ip=ip)
        subject = self._make_inbound("int-subject", "+7 930 000-00-03", ip=ip)
        subject.trust_level = TrustLevel.INTERNAL
        subject.save(update_fields=["trust_level"])

        messages = build_messages(inbound=subject)
        data = json.loads(messages[1]["content"].split("\n", 1)[1])

        self.assertIsNone(data.get("fingerprint_cluster"))

    def test_system_prompt_mentions_fingerprint_cluster(self):
        """SYSTEM_PROMPT must contain the fingerprint_cluster guidance."""
        from ai.prompt import SYSTEM_PROMPT
        self.assertIn("fingerprint_cluster", SYSTEM_PROMPT)
