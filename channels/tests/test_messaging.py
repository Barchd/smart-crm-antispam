from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ai.schemas import AIAnalysis
from ai.prompt import conversation_context_for_prompt
from bot.models import BotSettings
from channels.models import Channel, ChannelType, DeliveryLog, DeliveryStatus, Dialog, Message, MessageDirection, MessageStatus
from channels.services import conversation_context_for_inbound, send_dialog_message
from crm.models import Client, Deal, RoleChoices
from crm.phones import normalize_phone
from crm.services import create_deal
from intake.models import InboundRequest, InboundRequestStatus
from intake.services import payload_hash, process_request_by_rules


class MessagingInboxTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.head = user_model.objects.create_user(username="head", password="secret", full_name="Head", role=RoleChoices.HEAD)
        self.manager1 = user_model.objects.create_user(username="manager1", password="secret", full_name="Manager One", role=RoleChoices.MANAGER)
        self.manager2 = user_model.objects.create_user(username="manager2", password="secret", full_name="Manager Two", role=RoleChoices.MANAGER)
        self.client1 = Client.objects.create(
            name="Client One",
            phone_raw="+7 999 111-11-11",
            phone_normalized=normalize_phone("+7 999 111-11-11"),
            manager=self.manager1,
        )

    def inbound(self, *, external_id="msg-1", text="Здравствуйте, хочу купить авто", chat_id="site-chat-1") -> InboundRequest:
        payload = {"phone": "+7 999 333-33-33", "text": text, "chat_id": chat_id, "message_id": external_id}
        return InboundRequest.objects.create(
            external_id=external_id,
            source_type="site",
            source_name="site chat",
            name_raw="Lead",
            phone_raw=payload["phone"],
            email_raw="lead@example.test",
            message_text=text,
            raw_payload_json=payload,
            payload_hash=payload_hash(payload),
            ip_address="127.0.0.1",
            status=InboundRequestStatus.RECEIVED,
            ai_suggested_reply="Здравствуйте! Подскажите бюджет и желаемую модель.",
        )

    def create_dialog(self, *, deal: Deal | None = None) -> Dialog:
        deal = deal or create_deal(client=self.client1, title="Chat Deal", manager=self.manager1, user=self.head, reply_draft="Черновик ответа")
        channel = Channel.objects.create(type=ChannelType.SITE, name="site chat")
        dialog = Dialog.objects.create(channel=channel, client=deal.client, deal=deal, external_thread_id="site-chat-1")
        Message.objects.create(dialog=dialog, direction=MessageDirection.INBOUND, status=MessageStatus.RECEIVED, text="Есть ли авто в наличии?")
        return dialog

    def create_telegram_dialog(self, *, deal: Deal | None = None) -> Dialog:
        deal = deal or create_deal(client=self.client1, title="Telegram Deal", manager=self.manager1, user=self.head, reply_draft="Черновик Telegram")
        channel = Channel.objects.create(type=ChannelType.TELEGRAM, name="telegram")
        dialog = Dialog.objects.create(channel=channel, client=deal.client, deal=deal, external_thread_id="100500")
        Message.objects.create(dialog=dialog, direction=MessageDirection.INBOUND, status=MessageStatus.RECEIVED, text="Интересует авто из Telegram")
        return dialog

    def test_inbound_request_creates_dialog_and_inbound_message(self):
        inbound = self.inbound()

        processed = process_request_by_rules(inbound=inbound)

        self.assertEqual(processed.status, InboundRequestStatus.PROCESSED)
        dialog = Dialog.objects.get(deal=processed.linked_deal)
        self.assertEqual(dialog.channel.type, ChannelType.SITE)
        self.assertEqual(dialog.external_thread_id, "site-chat-1")
        message = dialog.messages.get(direction=MessageDirection.INBOUND)
        self.assertEqual(message.text, "Здравствуйте, хочу купить авто")
        self.assertEqual(processed.linked_deal.reply_draft, "Здравствуйте! Подскажите бюджет и желаемую модель.")

    def test_prompt_context_does_not_duplicate_current_inbound_message(self):
        dialog = self.create_dialog()
        Message.objects.create(
            dialog=dialog,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            text="У вас есть BMW?",
        )
        inbound = self.inbound(text="У вас есть BMW?", chat_id=dialog.external_thread_id)

        context = conversation_context_for_inbound(inbound=inbound)

        self.assertEqual(context.count("клиент: У вас есть BMW?"), 1)

    def test_ai_prompt_context_keeps_messages_older_than_twenty(self):
        dialog = self.create_telegram_dialog()
        Message.objects.create(
            dialog=dialog,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            text="Старый важный сигнал: две ссылки https://a.test https://b.test",
            external_message_id="old-risk",
        )
        for index in range(25):
            Message.objects.create(
                dialog=dialog,
                direction=MessageDirection.INBOUND,
                status=MessageStatus.RECEIVED,
                text=f"Обычное продолжение {index}",
                external_message_id=f"message-{index}",
            )
        inbound = self.inbound(text="Текущий вопрос", chat_id=dialog.external_thread_id)
        inbound.source_type = "telegram"
        inbound.raw_payload_json = {
            "user_id": dialog.external_thread_id,
            "message_id": "current",
            "text": inbound.message_text,
        }
        inbound.save(update_fields=["source_type", "raw_payload_json"])

        context = conversation_context_for_prompt(inbound)

        self.assertIn("Старый важный сигнал", context)
        self.assertIn("клиент: Текущий вопрос", context)

    def test_deal_detail_shows_chat_and_editable_suggested_reply(self):
        dialog = self.create_dialog()
        self.client.force_login(self.manager1)

        response = self.client.get(reverse("deal_detail", kwargs={"pk": dialog.deal_id}))

        self.assertContains(response, "Чат с клиентом")
        self.assertContains(response, "Канал обращения")
        self.assertContains(response, "Сайт")
        self.assertContains(response, "site-chat-1")
        self.assertContains(response, "Есть ли авто в наличии?")
        self.assertContains(response, "Черновик ответа")
        self.assertContains(response, "Отправить в канал клиента")
        self.assertContains(response, "Запросить новый AI-ответ")
        self.assertEqual(Message.objects.filter(dialog=dialog, direction=MessageDirection.OUTBOUND).count(), 0)

    def test_manager_regenerates_reply_draft_with_prompt_without_sending(self):
        dialog = self.create_dialog()
        self.client.force_login(self.manager1)

        generated = AIAnalysis(
            topic="наличие автомобиля",
            need="уточнить наличие",
            urgency="medium",
            category="purchase",
            spam_probability=0.01,
            toxicity=0.0,
            troll_probability=0.0,
            off_topic_probability=0.0,
            moderation_labels=[],
            department="sales",
            suggested_employee_id=None,
            summary="Клиент спрашивает про наличие.",
            suggested_reply="Здравствуйте! Автомобиль есть в наличии, можем записать вас на просмотр.",
        )

        with patch("ai.replies.create_ai_client") as create_client:
            create_client.return_value.analyze.return_value = generated
            response = self.client.post(
                reverse("deal_reply_regenerate", kwargs={"pk": dialog.deal_id}),
                {"dialog": dialog.pk, "prompt": "Ответь кратко и предложи просмотр."},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        dialog.deal.refresh_from_db()
        self.assertEqual(dialog.deal.reply_draft, generated.suggested_reply)
        self.assertFalse(Message.objects.filter(dialog=dialog, direction=MessageDirection.OUTBOUND).exists())
        create_client.return_value.analyze.assert_called_once()
        inbound_arg = create_client.return_value.analyze.call_args.kwargs["inbound"]
        self.assertIn("Текущий предложенный ответ", inbound_arg.message_text)
        self.assertIn("Черновик ответа", inbound_arg.message_text)
        self.assertIn("Ответь кратко и предложи просмотр.", inbound_arg.message_text)
        self.assertFalse(inbound_arg.is_follow_up)

    def test_regenerated_reply_marks_follow_up_after_manager_message(self):
        dialog = self.create_dialog()
        Message.objects.create(
            dialog=dialog,
            direction=MessageDirection.OUTBOUND,
            status=MessageStatus.SENT,
            text="Здравствуйте! Чем помочь?",
            sent_by=self.manager1,
        )
        self.client.force_login(self.manager1)

        generated = AIAnalysis(
            topic="наличие автомобиля",
            need="ответить по наличию",
            urgency="medium",
            category="purchase",
            spam_probability=0.01,
            toxicity=0.0,
            troll_probability=0.0,
            off_topic_probability=0.0,
            moderation_labels=[],
            department="sales",
            suggested_employee_id=None,
            summary="Продолжение разговора.",
            suggested_reply="Да, автомобиль доступен для заказа.",
        )

        with patch("ai.replies.create_ai_client") as create_client:
            create_client.return_value.analyze.return_value = generated
            response = self.client.post(
                reverse("deal_reply_regenerate", kwargs={"pk": dialog.deal_id}),
                {"dialog": dialog.pk, "prompt": "Ответь без приветствия."},
            )

        self.assertEqual(response.status_code, 302)
        inbound_arg = create_client.return_value.analyze.call_args.kwargs["inbound"]
        self.assertTrue(inbound_arg.is_follow_up)

    def test_manager_cannot_regenerate_reply_for_foreign_deal(self):
        foreign_client = Client.objects.create(
            name="Foreign Client",
            phone_raw="+7 999 444-44-44",
            phone_normalized=normalize_phone("+7 999 444-44-44"),
            manager=self.manager2,
        )
        foreign_deal = create_deal(client=foreign_client, title="Foreign Deal", manager=self.manager2, user=self.head)
        dialog = self.create_dialog(deal=foreign_deal)
        self.client.force_login(self.manager1)

        response = self.client.post(
            reverse("deal_reply_regenerate", kwargs={"pk": foreign_deal.pk}),
            {"dialog": dialog.pk, "prompt": "Ответь клиенту."},
        )

        self.assertEqual(response.status_code, 404)

    def test_manager_sends_edited_reply_to_dialog_channel(self):
        dialog = self.create_dialog()
        self.client.force_login(self.manager1)

        response = self.client.post(
            reverse("deal_message_send", kwargs={"pk": dialog.deal_id}),
            {"dialog": dialog.pk, "text": "Здравствуйте! Машина в наличии, можем записать на просмотр."},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        outbound = Message.objects.get(dialog=dialog, direction=MessageDirection.OUTBOUND)
        self.assertEqual(outbound.status, MessageStatus.SENT)
        self.assertEqual(outbound.sent_by, self.manager1)
        self.assertEqual(outbound.text, "Здравствуйте! Машина в наличии, можем записать на просмотр.")
        self.assertTrue(DeliveryLog.objects.filter(message=outbound, status="success", adapter="site").exists())
        dialog.deal.refresh_from_db()
        self.assertEqual(dialog.deal.reply_draft, outbound.text)
        self.assertIsNotNone(dialog.deal.reply_approved_at)

    def test_telegram_send_checks_bot_and_confirms_message_sent(self):
        dialog = self.create_telegram_dialog()
        BotSettings.objects.create(pk=1, bot_token="123456:telegram-token", admin_chat_id="100")
        self.client.force_login(self.manager1)

        with patch("bot.config.httpx.get") as get_me, patch("channels.adapters.httpx.post") as send_message:
            get_me.return_value = httpx.Response(
                200,
                json={"ok": True, "result": {"username": "crm_test_bot"}},
                request=httpx.Request("GET", "https://api.telegram.org/bot123456:telegram-token/getMe"),
            )
            send_message.return_value = httpx.Response(
                200,
                json={"ok": True, "result": {"message_id": 777}},
                request=httpx.Request("POST", "https://api.telegram.org/bot123456:telegram-token/sendMessage"),
            )
            response = self.client.post(
                reverse("deal_message_send", kwargs={"pk": dialog.deal_id}),
                {"dialog": dialog.pk, "text": "Здравствуйте! Отправляю ответ в Telegram."},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        get_me.assert_called_once()
        send_message.assert_called_once()
        outbound = Message.objects.get(dialog=dialog, direction=MessageDirection.OUTBOUND)
        self.assertEqual(outbound.status, MessageStatus.SENT)
        self.assertEqual(outbound.external_message_id, "777")
        delivery = DeliveryLog.objects.get(message=outbound)
        self.assertEqual(delivery.status, DeliveryStatus.SUCCESS)
        self.assertEqual(delivery.adapter, "telegram")
        self.assertEqual(delivery.response_json["result"]["message_id"], 777)

    def test_telegram_send_does_not_call_send_message_when_bot_unavailable(self):
        dialog = self.create_telegram_dialog()
        BotSettings.objects.create(pk=1, bot_token="123456:sensitive-token", admin_chat_id="100")
        self.client.force_login(self.manager1)

        with patch("bot.config.httpx.get", side_effect=httpx.ConnectError("boom 123456:sensitive-token")) as get_me:
            with patch("channels.adapters.httpx.post") as send_message:
                response = self.client.post(
                    reverse("deal_message_send", kwargs={"pk": dialog.deal_id}),
                    {"dialog": dialog.pk, "text": "Этот текст не должен уйти"},
                    follow=True,
                )

        self.assertEqual(response.status_code, 200)
        get_me.assert_called_once()
        send_message.assert_not_called()
        outbound = Message.objects.get(dialog=dialog, direction=MessageDirection.OUTBOUND)
        self.assertEqual(outbound.status, MessageStatus.FAILED)
        delivery = DeliveryLog.objects.get(message=outbound)
        self.assertEqual(delivery.status, DeliveryStatus.FAILED)
        self.assertNotIn("123456:sensitive-token", delivery.error)
        self.assertIn("Telegram bot недоступен", delivery.error)

    def test_telegram_send_is_refused_for_blocked_dialog(self):
        dialog = self.create_telegram_dialog()
        dialog.deal.is_spam = True
        dialog.deal.save(update_fields=["is_spam"])
        BotSettings.objects.create(pk=1, bot_token="123456:telegram-token", admin_chat_id="100")

        with patch("bot.config.httpx.get") as get_me, patch("channels.adapters.httpx.post") as send_message:
            outbound = send_dialog_message(
                dialog=dialog,
                deal=dialog.deal,
                text="Этот ответ не должен уйти",
                user=self.manager1,
            )

        get_me.assert_not_called()
        send_message.assert_not_called()
        self.assertEqual(outbound.status, MessageStatus.FAILED)
        delivery = DeliveryLog.objects.get(message=outbound)
        self.assertEqual(delivery.status, DeliveryStatus.FAILED)
        self.assertIn("заблокирован", delivery.error)

    def test_manager_cannot_send_to_foreign_deal_dialog(self):
        foreign_client = Client.objects.create(
            name="Foreign Client",
            phone_raw="+7 999 222-22-22",
            phone_normalized=normalize_phone("+7 999 222-22-22"),
            manager=self.manager2,
        )
        foreign_deal = create_deal(client=foreign_client, title="Foreign Deal", manager=self.manager2, user=self.head)
        dialog = self.create_dialog(deal=foreign_deal)
        self.client.force_login(self.manager1)

        response = self.client.post(reverse("deal_message_send", kwargs={"pk": foreign_deal.pk}), {"dialog": dialog.pk, "text": "Не должен уйти"})

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Message.objects.filter(dialog=dialog, direction=MessageDirection.OUTBOUND).exists())

    def test_deals_with_new_messages_are_bumped_to_top(self):
        older_deal = create_deal(client=self.client1, title="Older Deal", manager=self.manager1, user=self.head)
        newer_deal = create_deal(client=self.client1, title="Fresh Message Deal", manager=self.manager1, user=self.head)
        older_deal.created_at = timezone.now()
        older_deal.save(update_fields=["created_at"])
        newer_deal.created_at = timezone.now() - timedelta(days=1)
        newer_deal.save(update_fields=["created_at"])
        dialog = self.create_dialog(deal=newer_deal)
        dialog.last_message_at = timezone.now() + timedelta(minutes=1)
        dialog.save(update_fields=["last_message_at"])
        self.client.force_login(self.manager1)

        response = self.client.get(reverse("deals"))
        content = response.content.decode()

        self.assertLess(content.index("Fresh Message Deal"), content.index("Older Deal"))

    def test_repeat_telegram_message_reuses_existing_open_deal(self):
        existing_deal = create_deal(
            client=self.client1,
            title="Заявка telegram bot",
            manager=self.manager1,
            user=self.head,
            reply_draft="Старый черновик",
        )
        channel = Channel.objects.create(type=ChannelType.TELEGRAM, name="telegram")
        dialog = Dialog.objects.create(channel=channel, client=self.client1, deal=existing_deal, external_thread_id="777")
        payload = {"phone": self.client1.phone_raw, "text": "Добавьте ссылки на комплектации", "chat_id": 777, "message_id": 42}
        inbound = InboundRequest.objects.create(
            external_id="tg-lead:777:42",
            source_type="telegram",
            source_name="Telegram",
            name_raw=self.client1.name,
            phone_raw=self.client1.phone_raw,
            message_text=payload["text"],
            raw_payload_json=payload,
            payload_hash=payload_hash(payload),
            status=InboundRequestStatus.RECEIVED,
            ai_topic="ссылки на комплектации",
            ai_suggested_reply="Конечно, отправлю ссылки на комплектации.",
        )

        processed = process_request_by_rules(inbound=inbound)

        processed.refresh_from_db()
        existing_deal.refresh_from_db()
        dialog.refresh_from_db()
        self.assertEqual(processed.linked_deal, existing_deal)
        self.assertEqual(Deal.objects.filter(client=self.client1).count(), 1)
        self.assertEqual(existing_deal.title, "ссылки на комплектации")
        self.assertEqual(existing_deal.reply_draft, "Конечно, отправлю ссылки на комплектации.")
        self.assertEqual(dialog.messages.filter(direction=MessageDirection.INBOUND).count(), 1)
        self.assertEqual(dialog.messages.get(direction=MessageDirection.INBOUND).text, "Добавьте ссылки на комплектации")

    def test_repeat_telegram_message_reuses_client_and_deal_by_tg_user_id_even_when_phone_differs(self):
        existing_deal = create_deal(
            client=self.client1,
            title="Подбор автомобиля",
            manager=self.manager1,
            user=self.head,
            reply_draft="Старый черновик",
        )
        channel = Channel.objects.create(type=ChannelType.TELEGRAM, name="telegram")
        dialog = Dialog.objects.create(channel=channel, client=self.client1, deal=existing_deal, external_thread_id="777")
        payload = {
            "phone": "+7 999 999-99-99",
            "text": "Хочу узнать про трейд-ин",
            "chat_id": 999999,
            "user_id": 777,
            "message_id": 43,
        }
        inbound = InboundRequest.objects.create(
            external_id="tg-lead:777:43",
            source_type="telegram",
            source_name="Telegram",
            name_raw="Telegram User",
            phone_raw=payload["phone"],
            message_text=payload["text"],
            raw_payload_json=payload,
            payload_hash=payload_hash(payload),
            status=InboundRequestStatus.RECEIVED,
        )

        processed = process_request_by_rules(inbound=inbound)

        processed.refresh_from_db()
        dialog.refresh_from_db()
        self.assertEqual(processed.linked_client, self.client1)
        self.assertEqual(processed.linked_deal, existing_deal)
        self.assertEqual(Deal.objects.count(), 1)
        self.assertEqual(dialog.external_thread_id, "777")
