from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.test import TestCase

from ai.schemas import AIAnalysis
from ai.services import process_request_with_ai
from bot.customer import (
    LeadFlow,
    build_lead_from_message,
    create_telegram_inbound_request,
    customer_name_handler,
    customer_phone_handler,
    customer_question_handler,
    customer_start_handler,
    phone_keyboard,
    route_telegram_customer_message,
)
from channels.models import Channel, ChannelType, Dialog, Message, MessageDirection
from crm.models import Client, Deal, RoleChoices
from crm.phones import normalize_phone
from crm.services import create_deal
from intake.models import InboundRequest, InboundRequestStatus, ProcessingLog


class FakeState:
    def __init__(self):
        self.state = None
        self.data = {}

    async def clear(self):
        self.state = None
        self.data = {}

    async def set_state(self, state):
        self.state = state

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def get_data(self):
        return dict(self.data)


class FakeMessage:
    def __init__(self, *, text="", contact=None, voice=None, message_id=1, user_id=777, chat_id=777):
        self.text = text
        self.contact = contact
        self.voice = voice
        self.message_id = message_id
        self.from_user = SimpleNamespace(id=user_id, username="customer", language_code="ru")
        self.chat = SimpleNamespace(id=chat_id)
        self.bot = SimpleNamespace()
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


class CustomerTelegramFlowTests(TestCase):
    def create_existing_telegram_dialog(self) -> Dialog:
        user_model = get_user_model()
        manager = user_model.objects.create_user(username="manager", password="secret", full_name="Manager", role=RoleChoices.MANAGER)
        client = Client.objects.create(
            name="Иван",
            phone_raw="+79991234567",
            phone_normalized=normalize_phone("+79991234567"),
            manager=manager,
        )
        deal = create_deal(client=client, title="Подбор автомобиля", manager=manager)
        channel = Channel.objects.create(type=ChannelType.TELEGRAM, name="Telegram")
        return Dialog.objects.create(channel=channel, client=client, deal=deal, external_thread_id="777")

    def test_phone_keyboard_requests_contact(self):
        button = phone_keyboard().keyboard[0][0]

        self.assertTrue(button.request_contact)

    def test_flow_asks_name_phone_and_question_before_creating_request(self):
        state = FakeState()
        start = FakeMessage(message_id=1)
        async_to_sync(customer_start_handler)(start, state)
        self.assertEqual(state.state, LeadFlow.waiting_name)
        self.assertIn("Как вас называть", start.answers[-1][0])

        name = FakeMessage(text="Иван", message_id=2)
        async_to_sync(customer_name_handler)(name, state)
        self.assertEqual(state.state, LeadFlow.waiting_phone)
        self.assertIn("отправьте телефон", name.answers[-1][0])

        phone = FakeMessage(
            contact=SimpleNamespace(phone_number="+79991234567", user_id=777),
            message_id=3,
        )
        async_to_sync(customer_phone_handler)(phone, state)
        self.assertEqual(state.state, LeadFlow.waiting_question)
        self.assertIn("ваш вопрос", phone.answers[-1][0])
        self.assertEqual(self._request_count(), 0)

        question = FakeMessage(text="Есть ли автомобиль в наличии?", message_id=4)
        async_to_sync(customer_question_handler)(question, state)

        self.assertEqual(state.state, LeadFlow.waiting_question)
        self.assertEqual(self._request_count(), 1)
        inbound = self._request()
        self.assertEqual(inbound.name_raw, "Иван")
        self.assertEqual(inbound.phone_raw, "+79991234567")
        self.assertEqual(inbound.message_text, "Есть ли автомобиль в наличии?")
        self.assertEqual(inbound.source_type, "telegram")
        self.assertEqual(inbound.source_name, "Telegram")
        self.assertEqual(inbound.status, InboundRequestStatus.RECEIVED)
        self.assertEqual(question.answers, [])

    def test_start_existing_dialog_skips_name_and_phone_questions(self):
        self.create_existing_telegram_dialog()
        state = FakeState()
        start = FakeMessage(message_id=20)

        async_to_sync(customer_start_handler)(start, state)

        self.assertEqual(state.state, LeadFlow.waiting_question)
        self.assertEqual(state.data["name"], "Иван")
        self.assertEqual(state.data["phone"], "+79991234567")
        self.assertIn("Напишите ваш вопрос", start.answers[-1][0])
        self.assertIn("Менеджер ответит здесь", start.answers[-1][0])
        self.assertNotIn("Как вас называть", start.answers[-1][0])

    def test_start_existing_dialog_uses_telegram_user_id_not_chat_id(self):
        self.create_existing_telegram_dialog()
        state = FakeState()
        start = FakeMessage(message_id=20, user_id=777, chat_id=-100777)

        async_to_sync(customer_start_handler)(start, state)

        self.assertEqual(state.state, LeadFlow.waiting_question)
        self.assertEqual(state.data["name"], "Иван")
        self.assertIn("Напишите ваш вопрос", start.answers[-1][0])
        self.assertIn("Менеджер ответит здесь", start.answers[-1][0])

    def test_start_after_saved_request_skips_name_and_phone_even_before_dialog_exists(self):
        message = FakeMessage(message_id=30)
        lead = build_lead_from_message(
            message,
            name="Иван",
            phone="+79991234567",
            question="Первый вопрос клиента",
        )
        create_telegram_inbound_request(lead)
        state = FakeState()
        start_again = FakeMessage(message_id=31)

        async_to_sync(customer_start_handler)(start_again, state)

        self.assertEqual(state.state, LeadFlow.waiting_question)
        self.assertEqual(state.data["name"], "Иван")
        self.assertEqual(state.data["phone"], "+79991234567")
        self.assertIn("Напишите ваш вопрос", start_again.answers[-1][0])
        self.assertIn("Менеджер ответит здесь", start_again.answers[-1][0])
        self.assertNotIn("Как вас называть", start_again.answers[-1][0])
        self.assertNotIn("отправьте телефон", start_again.answers[-1][0])

    def test_blocked_telegram_customer_is_ignored_without_any_reply(self):
        first_message = FakeMessage(message_id=32)
        inbound = create_telegram_inbound_request(
            build_lead_from_message(
                first_message,
                name="Иван",
                phone="+79991234567",
                question="Первый вопрос клиента",
            )
        )
        inbound.status = InboundRequestStatus.BLOCKED
        inbound.save(update_fields=["status"])

        start = FakeMessage(message_id=33)
        async_to_sync(customer_start_handler)(start, FakeState())

        from bot.customer import customer_fallback_handler

        follow_up = FakeMessage(text="Новый вопрос от заблокированного клиента", message_id=34)
        async_to_sync(customer_fallback_handler)(follow_up)

        self.assertEqual(start.answers, [])
        self.assertEqual(follow_up.answers, [])
        self.assertEqual(self._request_count(), 1)

    def test_blocked_telegram_customer_cannot_be_routed_directly(self):
        first_message = FakeMessage(message_id=35)
        inbound = create_telegram_inbound_request(
            build_lead_from_message(
                first_message,
                name="Иван",
                phone="+79991234567",
                question="Первый вопрос клиента",
            )
        )
        inbound.status = InboundRequestStatus.BLOCKED
        inbound.save(update_fields=["status"])

        routed = route_telegram_customer_message(
            build_lead_from_message(
                FakeMessage(text="Новый вопрос", message_id=36),
                name="Иван",
                phone="+79991234567",
                question="Новый вопрос",
            )
        )

        self.assertIsNone(routed)
        self.assertEqual(self._request_count(), 1)

    def test_fallback_after_saved_request_reuses_same_request_before_dialog_exists(self):
        first_message = FakeMessage(message_id=40)
        lead = build_lead_from_message(
            first_message,
            name="Иван",
            phone="+79991234567",
            question="Первый вопрос клиента",
        )
        create_telegram_inbound_request(lead)
        message = FakeMessage(text="Второй вопрос без повторной анкеты", message_id=41)

        from bot.customer import customer_fallback_handler

        async_to_sync(customer_fallback_handler)(message)

        self.assertEqual(self._request_count(), 1)
        inbound = self._request()
        self.assertEqual(inbound.name_raw, "Иван")
        self.assertEqual(inbound.phone_raw, "+79991234567")
        self.assertEqual(inbound.message_text, "Второй вопрос без повторной анкеты")
        self.assertEqual(inbound.raw_payload_json["follow_up_messages"][0]["message_id"], 41)
        self.assertEqual(inbound.status, InboundRequestStatus.RECEIVED)
        self.assertEqual(message.answers, [])

    def test_fallback_from_existing_dialog_appends_message_without_request(self):
        dialog = self.create_existing_telegram_dialog()
        message = FakeMessage(text="А можно добавить ссылку на комплектации?", message_id=21)

        from bot.customer import customer_fallback_handler

        async_to_sync(customer_fallback_handler)(message)

        self.assertEqual(self._request_count(), 0)
        stored = Message.objects.get(dialog=dialog, direction=MessageDirection.INBOUND)
        self.assertEqual(stored.text, "А можно добавить ссылку на комплектации?")
        self.assertEqual(stored.external_message_id, "21")
        self.assertEqual(message.answers, [])

    def test_second_question_in_waiting_state_does_not_create_second_request(self):
        state = FakeState()
        state.state = LeadFlow.waiting_question
        state.data = {"name": "Иван", "phone": "+79991234567"}

        async_to_sync(customer_question_handler)(FakeMessage(text="Первый вопрос", message_id=50), state)
        async_to_sync(customer_question_handler)(FakeMessage(text="Второй вопрос", message_id=51), state)

        self.assertEqual(self._request_count(), 1)
        inbound = self._request()
        self.assertEqual(inbound.message_text, "Второй вопрос")
        self.assertEqual([item["text"] for item in inbound.raw_payload_json["follow_up_messages"]], ["Второй вопрос"])

    def test_int_and_string_telegram_user_id_reuse_one_inbound(self):
        first_message = FakeMessage(text="Первый вопрос", message_id=55, user_id=777)
        first = route_telegram_customer_message(
            build_lead_from_message(first_message, name="Иван", phone="+79991234567", question=first_message.text)
        )
        second_message = FakeMessage(text="Второй вопрос", message_id=56, user_id="777")

        second = route_telegram_customer_message(
            build_lead_from_message(second_message, name="Иван", phone="+79991234567", question=second_message.text)
        )

        first.refresh_from_db()
        self.assertEqual(InboundRequest.objects.count(), 1)
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(first.raw_payload_json["user_id"], "777")
        self.assertEqual(first.raw_payload_json["follow_up_messages"][0]["user_id"], "777")

    def test_first_message_sets_ai_topic_and_second_reuses_request_and_dialog(self):
        user_model = get_user_model()
        user_model.objects.create_user(username="manager", password="secret", full_name="Manager", role=RoleChoices.MANAGER)
        first_message = FakeMessage(text="Есть Haval Jolion в кредит?", message_id=60)
        first_lead = build_lead_from_message(
            first_message,
            name="Иван",
            phone="+79991234567",
            question=first_message.text,
        )
        inbound = route_telegram_customer_message(first_lead)
        first_analysis = AIAnalysis(
            topic="кредит на Haval Jolion",
            need="подобрать Haval Jolion в кредит",
            urgency="medium",
            category="credit",
            spam_probability=0.01,
            toxicity=0.0,
            troll_probability=0.0,
            off_topic_probability=0.0,
            moderation_labels=[],
            department="finance",
            suggested_employee_id=None,
            summary="Клиент интересуется Haval Jolion в кредит.",
            suggested_reply="Здравствуйте! Уточните желаемый первоначальный взнос.",
        )
        process_request_with_ai(inbound=inbound, client=SimpleNamespace(analyze=lambda **kwargs: first_analysis))
        inbound.refresh_from_db()

        first_deal_id = inbound.linked_deal_id
        self.assertEqual(inbound.linked_deal.title, "кредит на Haval Jolion")
        self.assertEqual(InboundRequest.objects.count(), 1)
        self.assertEqual(Dialog.objects.count(), 1)
        self.assertEqual(Deal.objects.count(), 1)

        second_message = FakeMessage(text="А можно без первого взноса?", message_id=61)
        second_lead = build_lead_from_message(
            second_message,
            name="Иван",
            phone="+79991234567",
            question=second_message.text,
        )
        same_inbound = route_telegram_customer_message(second_lead)
        second_analysis = AIAnalysis(
            topic="условия кредита на Haval Jolion",
            need="уточнить кредит без первоначального взноса",
            urgency="medium",
            category="credit",
            spam_probability=0.01,
            toxicity=0.0,
            troll_probability=0.0,
            off_topic_probability=0.0,
            moderation_labels=[],
            department="finance",
            suggested_employee_id=None,
            summary="Клиент уточняет возможность кредита без первого взноса.",
            suggested_reply="Да, есть программы без первоначального взноса; точные условия рассчитает менеджер.",
        )
        process_request_with_ai(inbound=same_inbound, client=SimpleNamespace(analyze=lambda **kwargs: second_analysis))

        self.assertEqual(self._request_count(), 1)
        same_inbound.refresh_from_db()
        self.assertEqual(same_inbound.pk, inbound.pk)
        self.assertEqual(same_inbound.linked_deal_id, first_deal_id)
        self.assertEqual(Dialog.objects.count(), 1)
        self.assertEqual(Deal.objects.count(), 1)
        dialog = Dialog.objects.get(deal=same_inbound.linked_deal)
        self.assertEqual(dialog.messages.filter(direction=MessageDirection.INBOUND).count(), 2)
        same_inbound.linked_deal.refresh_from_db()
        self.assertEqual(same_inbound.linked_deal.title, "условия кредита на Haval Jolion")
        self.assertEqual(
            same_inbound.linked_deal.reply_draft,
            "Да, есть программы без первоначального взноса; точные условия рассчитает менеджер.",
        )
        self.assertEqual(ProcessingLog.objects.filter(inbound_request=same_inbound, step="deal_created").count(), 1)
        self.assertTrue(ProcessingLog.objects.filter(inbound_request=same_inbound, step="deal_reused").exists())

    def test_follow_up_refreshes_all_ai_risk_metrics_on_same_request(self):
        user_model = get_user_model()
        user_model.objects.create_user(username="manager", password="secret", full_name="Manager", role=RoleChoices.MANAGER)
        first_message = FakeMessage(text="Хочу подобрать Haval", message_id=70)
        inbound = route_telegram_customer_message(
            build_lead_from_message(first_message, name="Иван", phone="+79991234567", question=first_message.text)
        )
        first_analysis = AIAnalysis(
            topic="подбор Haval",
            need="подобрать автомобиль",
            urgency="medium",
            category="purchase",
            spam_probability=0.02,
            toxicity=0.01,
            troll_probability=0.0,
            off_topic_probability=0.0,
            moderation_labels=[],
            department="sales",
            suggested_employee_id=None,
            summary="Клиент выбирает Haval.",
            suggested_reply="Здравствуйте! Уточните модель.",
        )
        process_request_with_ai(inbound=inbound, client=SimpleNamespace(analyze=lambda **kwargs: first_analysis))
        inbound.refresh_from_db()
        original_deal_id = inbound.linked_deal_id

        follow_up = FakeMessage(text="Это уже не по теме", message_id=71)
        same_inbound = route_telegram_customer_message(
            build_lead_from_message(follow_up, name="Иван", phone="+79991234567", question=follow_up.text)
        )
        second_analysis = AIAnalysis(
            topic="нецелевое продолжение",
            need="ручная модерация диалога",
            urgency="low",
            category="other",
            spam_probability=0.33,
            toxicity=0.72,
            troll_probability=0.61,
            off_topic_probability=0.64,
            moderation_labels=["toxicity", "troll", "off_topic"],
            department="sales",
            suggested_employee_id=None,
            summary="Follow-up требует ручной модерации.",
            suggested_reply="Менеджеру предложено проверить контекст.",
        )
        process_request_with_ai(inbound=same_inbound, client=SimpleNamespace(analyze=lambda **kwargs: second_analysis))

        same_inbound.refresh_from_db()
        self.assertEqual(InboundRequest.objects.count(), 1)
        self.assertEqual(Deal.objects.count(), 1)
        self.assertEqual(Deal.objects.filter(is_spam=False).count(), 0)
        self.assertEqual(same_inbound.linked_deal_id, original_deal_id)
        self.assertEqual(same_inbound.status, InboundRequestStatus.SUSPICIOUS)
        self.assertTrue(same_inbound.linked_deal.is_spam)
        self.assertEqual(same_inbound.ai_spam_probability, 0.33)
        self.assertEqual(same_inbound.ai_toxicity, 0.72)
        self.assertEqual(same_inbound.ai_troll_probability, 0.61)
        self.assertEqual(same_inbound.ai_off_topic_probability, 0.64)
        self.assertEqual(same_inbound.ai_moderation_labels, ["toxicity", "troll", "off_topic"])
        self.assertEqual(same_inbound.ai_topic, "нецелевое продолжение")
        self.assertEqual(same_inbound.ai_summary, "Follow-up требует ручной модерации.")
        self.assertEqual(same_inbound.risk_score_final, 72)
        self.assertTrue(same_inbound.processing_logs.filter(step="rules_risk_scored").exists())
        self.assertTrue(same_inbound.processing_logs.filter(step="ai_analyzed").exists())

    def test_foreign_contact_is_rejected(self):
        state = FakeState()
        state.data = {"name": "Иван"}
        state.state = LeadFlow.waiting_phone
        message = FakeMessage(
            contact=SimpleNamespace(phone_number="+79991234567", user_id=999),
            message_id=3,
        )

        async_to_sync(customer_phone_handler)(message, state)

        self.assertEqual(state.state, LeadFlow.waiting_phone)
        self.assertIn("именно ваш контакт", message.answers[-1][0])
        self.assertEqual(self._request_count(), 0)

    def test_build_and_persist_lead_keeps_question_payload(self):
        message = FakeMessage(message_id=10)
        lead = build_lead_from_message(
            message,
            name="Петр",
            phone="+79990000000",
            question="Можно ли записаться на тест-драйв?",
        )
        inbound = create_telegram_inbound_request(lead)

        self.assertEqual(inbound.raw_payload_json["text"], "Можно ли записаться на тест-драйв?")
        self.assertEqual(inbound.raw_payload_json["chat_id"], 777)
        self.assertEqual(inbound.raw_payload_json["user_id"], "777")
        self.assertEqual(inbound.raw_payload_json["language_code"], "ru")

    def test_voice_question_is_transcribed_before_request_creation(self):
        state = FakeState()
        state.state = LeadFlow.waiting_question
        state.data = {"name": "Иван", "phone": "+79991234567"}
        message = FakeMessage(voice=SimpleNamespace(file_id="voice-1", duration=5, file_size=1000), message_id=5)

        with patch(
            "bot.customer.transcribe_telegram_voice",
            new=AsyncMock(return_value=SimpleNamespace(ok=True, text="Подскажите наличие Haval Jolion", error="")),
        ):
            async_to_sync(customer_question_handler)(message, state)

        self.assertEqual(state.state, LeadFlow.waiting_question)
        inbound = self._request()
        self.assertEqual(inbound.message_text, "Подскажите наличие Haval Jolion")
        self.assertEqual(inbound.raw_payload_json["text"], "Подскажите наличие Haval Jolion")
        self.assertIn("распознаю", message.answers[0][0])
        self.assertEqual(len(message.answers), 1)

    def test_failed_voice_transcription_does_not_create_request(self):
        state = FakeState()
        state.state = LeadFlow.waiting_question
        state.data = {"name": "Иван", "phone": "+79991234567"}
        message = FakeMessage(voice=SimpleNamespace(file_id="voice-1", duration=5, file_size=1000), message_id=5)

        with patch(
            "bot.customer.transcribe_telegram_voice",
            new=AsyncMock(return_value=SimpleNamespace(ok=False, text="", error="OpenAI API key не задан.")),
        ):
            async_to_sync(customer_question_handler)(message, state)

        self.assertEqual(state.state, LeadFlow.waiting_question)
        self.assertEqual(self._request_count(), 0)
        self.assertIn("Напишите, пожалуйста, вопрос текстом", message.answers[-1][0])

    @staticmethod
    def _request_count():
        from intake.models import InboundRequest

        return InboundRequest.objects.count()

    @staticmethod
    def _request():
        from intake.models import InboundRequest

        return InboundRequest.objects.get()
