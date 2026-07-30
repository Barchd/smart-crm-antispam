from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from channels.models import Channel, ChannelType, Dialog, Message, MessageDirection, MessageStatus
from crm.models import Client, DealLogAction, DealStage, RoleChoices
from crm.phones import normalize_phone
from crm.services import create_deal
from intake.models import Blocklist, BlocklistKind, InboundRequest, InboundRequestStatus, ProcessingLog
from intake.services import payload_hash


class CrmUiTests(TestCase):
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

    def test_manager_creates_client_and_duplicate_is_neutral(self):
        self.client.force_login(self.manager1)
        response = self.client.post(
            reverse("client_create"),
            {
                "name": "New Client",
                "phone_raw": "+7 999 333-33-33",
                "email": "new@example.test",
                "source": "manual",
                "manager": self.manager2.pk,
                "comment": "note",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        created = Client.objects.get(phone_normalized="+79993333333")
        self.assertEqual(created.manager, self.manager1)

        response = self.client.post(
            reverse("client_create"),
            {
                "name": "Duplicate",
                "phone_raw": "8 (999) 111-11-11",
                "email": "",
                "source": "manual",
                "manager": self.manager1.pk,
                "comment": "",
            },
        )
        self.assertContains(response, "Клиент с таким номером уже существует")

    def test_manager_creates_deal_changes_stage_comments_and_approves_reply(self):
        self.client.force_login(self.manager1)
        response = self.client.post(
            reverse("deal_create"),
            {
                "client": self.client1.pk,
                "title": "Manual Deal",
                "amount": "100000.00",
                "manager": self.manager2.pk,
                "next_contact_at": "",
                "reply_draft": "Здравствуйте, готовы обсудить авто.",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        deal = self.client1.deals.get(title="Manual Deal")
        self.assertEqual(deal.manager, self.manager1)

        self.client.post(
            reverse("deal_detail", kwargs={"pk": deal.pk}),
            {
                "title": "Manual Deal Updated",
                "amount": "120000.00",
                "manager": self.manager2.pk,
                "next_contact_at": "",
                "reply_draft": "Обновленный черновик",
            },
        )
        self.client.post(
            reverse("deal_stage_change", kwargs={"pk": deal.pk}),
            {"stage": DealStage.FIRST_CONTACT},
        )
        deal.refresh_from_db()
        self.assertEqual(deal.title, "Manual Deal Updated")
        self.assertEqual(str(deal.amount), "120000.00")
        self.assertEqual(deal.stage, DealStage.FIRST_CONTACT)
        self.assertEqual(deal.manager, self.manager1)
        self.assertTrue(deal.logs.filter(action=DealLogAction.STAGE_CHANGED).exists())

        self.client.post(reverse("deal_comment_add", kwargs={"pk": deal.pk}), {"text": "Клиент ждет звонок"})
        self.assertEqual(deal.comments.count(), 1)
        self.assertTrue(deal.logs.filter(action=DealLogAction.COMMENT_ADDED).exists())

        self.client.post(reverse("deal_reply_approve", kwargs={"pk": deal.pk}))
        deal.refresh_from_db()
        self.assertIsNotNone(deal.reply_approved_at)
        self.assertEqual(deal.reply_approved_by, self.manager1)
        self.assertTrue(deal.logs.filter(action=DealLogAction.REPLY_APPROVED).exists())

    def test_head_changes_responsible_with_log(self):
        deal = create_deal(client=self.client1, title="Head Deal", manager=self.manager1, user=self.head)
        self.client.force_login(self.head)
        self.client.post(
            reverse("deal_detail", kwargs={"pk": deal.pk}),
            {
                "title": "Head Deal",
                "amount": "0",
                "manager": self.manager2.pk,
                "next_contact_at": "",
                "reply_draft": "",
            },
        )
        deal.refresh_from_db()
        self.assertEqual(deal.manager, self.manager2)
        self.assertTrue(deal.logs.filter(action=DealLogAction.MANAGER_CHANGED).exists())

    def test_deal_history_is_human_readable_and_chronological(self):
        deal = create_deal(client=self.client1, title="History Deal", manager=self.manager1, user=self.head)
        self.client.force_login(self.head)
        self.client.post(reverse("deal_stage_change", kwargs={"pk": deal.pk}), {"stage": DealStage.LOST})

        response = self.client.get(reverse("deal_detail", kwargs={"pk": deal.pk}))
        content = response.content.decode()

        self.assertContains(response, "Сделка создана")
        self.assertContains(response, "ответственный: Manager One")
        self.assertContains(response, "Ответственный назначен: Manager One")
        self.assertContains(response, "Этап изменен")
        self.assertContains(response, "Новая заявка → Отказ")
        self.assertNotContains(response, "deal_created")
        self.assertNotContains(response, "new → lost")
        self.assertNotContains(response, f"→ {deal.pk}")
        self.assertLess(content.index("Сделка создана"), content.index("Этап изменен"))

    def test_deal_history_shows_manager_assignment_and_change(self):
        deal = create_deal(client=self.client1, title="Manager History", manager=self.manager1, user=self.head)
        self.client.force_login(self.head)
        self.client.post(
            reverse("deal_detail", kwargs={"pk": deal.pk}),
            {
                "title": "Manager History",
                "amount": "0",
                "manager": self.manager2.pk,
                "next_contact_at": "",
                "reply_draft": "",
            },
        )

        response = self.client.get(reverse("deal_detail", kwargs={"pk": deal.pk}))
        self.assertContains(response, "ответственный: Manager One")
        self.assertContains(response, "Ответственный назначен: Manager One")
        self.assertContains(response, "Ответственный: Manager One → Manager Two")

    def test_deal_history_falls_back_to_current_manager_for_old_created_log(self):
        deal = create_deal(client=self.client1, title="Fallback UI History", manager=self.manager1, user=self.head)
        deal.logs.filter(action=DealLogAction.DEAL_CREATED).update(new_value="")
        self.client.force_login(self.head)

        response = self.client.get(reverse("deal_detail", kwargs={"pk": deal.pk}))

        self.assertContains(response, "Сделка создана · ответственный: Manager One")
        self.assertNotContains(response, "Сделка создана · ответственный: не задан")

    def test_deal_edit_page_redirects_to_detail_card(self):
        deal = create_deal(client=self.client1, title="Inline Edit Deal", manager=self.manager1, user=self.head)
        self.client.force_login(self.manager1)

        response = self.client.get(reverse("deal_edit", kwargs={"pk": deal.pk}))

        self.assertRedirects(response, reverse("deal_detail", kwargs={"pk": deal.pk}))

    def test_deal_detail_contains_inline_edit_form_instead_of_edit_link(self):
        deal = create_deal(client=self.client1, title="Inline Form Deal", manager=self.manager1, user=self.head)
        self.client.force_login(self.manager1)

        response = self.client.get(reverse("deal_detail", kwargs={"pk": deal.pk}))

        self.assertContains(response, "Изменить сделку")
        self.assertContains(response, "Сохранить изменения")
        self.assertContains(response, "Воронка сделки")
        self.assertContains(response, "Этап меняется только через воронку")
        self.assertNotContains(response, 'id="id_stage"')
        self.assertNotContains(response, f'href="{reverse("deal_edit", kwargs={"pk": deal.pk})}"')

    def test_pipeline_only_links_allowed_next_stages(self):
        deal = create_deal(client=self.client1, title="Pipeline Deal", manager=self.manager1, user=self.head)
        self.client.force_login(self.manager1)

        response = self.client.get(reverse("deal_detail", kwargs={"pk": deal.pk}))

        self.assertContains(response, 'name="stage" value="first_contact"')
        self.assertContains(response, 'name="stage" value="lost"')
        self.assertNotContains(response, 'name="stage" value="qualification"')
        self.assertNotContains(response, 'name="stage" value="won"')
        self.assertContains(response, "Сначала завершите предыдущий этап")
        self.assertContains(response, "stage-new")
        self.assertContains(response, "stage-first-contact")

    def test_terminal_pipeline_is_read_only(self):
        deal = create_deal(client=self.client1, title="Closed Pipeline", manager=self.manager1, user=self.head)
        deal.stage = DealStage.WON
        deal.save(update_fields=["stage"])
        self.client.force_login(self.manager1)

        response = self.client.get(reverse("deal_detail", kwargs={"pk": deal.pk}))

        self.assertContains(response, "Сделка закрыта")
        self.assertNotContains(response, reverse("deal_stage_change", kwargs={"pk": deal.pk}))

    def test_deal_list_uses_shared_stage_color_badge(self):
        deal = create_deal(client=self.client1, title="Colored Stage", manager=self.manager1, user=self.head)
        deal.stage = DealStage.PROPOSAL
        deal.save(update_fields=["stage"])
        self.client.force_login(self.manager1)

        response = self.client.get(reverse("deals"))

        self.assertContains(response, "stage-proposal")
        self.assertContains(response, "Предложение")

    def test_invalid_pipeline_post_returns_400_without_stage_log(self):
        deal = create_deal(client=self.client1, title="No Skip Deal", manager=self.manager1, user=self.head)
        self.client.force_login(self.manager1)

        response = self.client.post(
            reverse("deal_stage_change", kwargs={"pk": deal.pk}),
            {"stage": DealStage.QUALIFICATION},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Нельзя перейти", status_code=400)
        deal.refresh_from_db()
        self.assertEqual(deal.stage, DealStage.NEW)
        self.assertFalse(deal.logs.filter(action=DealLogAction.STAGE_CHANGED).exists())

    def test_manager_can_move_own_deal_only_to_allowed_stage(self):
        deal = create_deal(client=self.client1, title="Manager Pipeline", manager=self.manager1, user=self.head)
        self.client.force_login(self.manager1)

        response = self.client.post(
            reverse("deal_stage_change", kwargs={"pk": deal.pk}),
            {"stage": DealStage.FIRST_CONTACT},
        )

        self.assertRedirects(response, reverse("deal_detail", kwargs={"pk": deal.pk}))
        deal.refresh_from_db()
        self.assertEqual(deal.stage, DealStage.FIRST_CONTACT)

    def test_head_deletes_deal_from_detail_card(self):
        deal = create_deal(client=self.client1, title="Delete Me", manager=self.manager1, user=self.head)
        self.client.force_login(self.head)

        response = self.client.post(reverse("deal_delete", kwargs={"pk": deal.pk}), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client1.deals.filter(pk=deal.pk).exists())
        self.assertContains(response, "Сделка «Delete Me» удалена")

    def test_manager_cannot_delete_own_deal(self):
        deal = create_deal(client=self.client1, title="Keep Me", manager=self.manager1, user=self.head)
        self.client.force_login(self.manager1)

        response = self.client.post(reverse("deal_delete", kwargs={"pk": deal.pk}))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.client1.deals.filter(pk=deal.pk).exists())

    def test_head_sees_delete_button_and_confirmation_modal_in_deals_list(self):
        deal = create_deal(client=self.client1, title="List Delete Deal", manager=self.manager1, user=self.head)
        self.client.force_login(self.head)

        response = self.client.get(reverse("deals"))

        self.assertContains(response, "Удалить")
        self.assertContains(response, f'data-bs-target="#deleteDealModal{deal.pk}"')
        self.assertContains(response, f'id="deleteDealModal{deal.pk}"')
        self.assertContains(response, "Удалить сделку?")
        self.assertContains(response, "Да, удалить")
        self.assertContains(response, reverse("deal_delete", kwargs={"pk": deal.pk}))

    def test_deals_list_shows_id_then_topic_columns(self):
        deal = create_deal(client=self.client1, title="Topic Column Deal", manager=self.manager1, user=self.head)
        self.client.force_login(self.manager1)

        response = self.client.get(reverse("deals"))
        content = response.content.decode()

        self.assertContains(response, "<th>ID</th>", html=True)
        self.assertContains(response, "<th>Тема</th>", html=True)
        self.assertContains(response, f"#{deal.pk}")
        self.assertContains(response, "Topic Column Deal")
        self.assertLess(content.index("<th>ID</th>"), content.index("<th>Тема</th>"))
        self.assertNotContains(response, "<th>Сделка</th>", html=True)

    def test_cyrillic_search_ignores_case_on_clients_and_deals(self):
        cyrillic_client = Client.objects.create(
            name="Иван Петров",
            phone_raw="+7 999 444-44-44",
            phone_normalized=normalize_phone("+7 999 444-44-44"),
            manager=self.manager1,
        )
        create_deal(client=cyrillic_client, title="Кредит на Tiggo", manager=self.manager1, user=self.head)
        self.client.force_login(self.manager1)

        clients_response = self.client.get(reverse("clients"), {"q": "иван"})
        self.assertContains(clients_response, "Иван Петров")

        deals_response = self.client.get(reverse("deals"), {"q": "кредит"})
        self.assertContains(deals_response, "Кредит на Tiggo")
        self.assertContains(deals_response, "Иван Петров")

    def test_manager_does_not_see_delete_action_in_deals_list(self):
        create_deal(client=self.client1, title="Manager Visible Deal", manager=self.manager1, user=self.head)
        self.client.force_login(self.manager1)

        response = self.client.get(reverse("deals"))

        self.assertContains(response, "Manager Visible Deal")
        self.assertNotContains(response, "Удалить сделку?")
        self.assertNotContains(response, "Да, удалить")
        self.assertNotContains(response, "deal_delete")

    def test_deal_detail_shows_required_ai_analysis_fields(self):
        inbound = self.create_ai_inbound()
        deal = create_deal(client=self.client1, title="Кредит на Chery Tiggo", manager=self.manager1, user=self.head, inbound_request_id=inbound.id)
        inbound.linked_client = self.client1
        inbound.linked_deal = deal
        inbound.ai_suggested_employee = self.manager1
        inbound.save(update_fields=["linked_client", "linked_deal", "ai_suggested_employee"])
        self.client.force_login(self.manager1)

        response = self.client.get(reverse("deal_detail", kwargs={"pk": deal.pk}))

        self.assertContains(response, "AI-анализ")
        self.assertContains(response, "Тема")
        self.assertContains(response, "Кредит на Chery Tiggo")
        self.assertContains(response, "Потребность")
        self.assertContains(response, "Рассчитать кредит и наличие автомобиля")
        self.assertContains(response, "Срочность")
        self.assertContains(response, "Высокая")
        self.assertContains(response, "Категория")
        self.assertContains(response, "Кредит")
        self.assertContains(response, "Вероятность спама")
        self.assertContains(response, "12%")
        self.assertContains(response, "Резюме")
        self.assertContains(response, "Клиент хочет Chery Tiggo в кредит.")
        self.assertContains(response, "Предложенный ответ")
        self.assertContains(response, "Здравствуйте! Рассчитаем кредит")
        self.assertNotContains(response, "Данные появятся после реализации intake")

    def test_head_inbound_requests_page_shows_ai_summary_and_classification(self):
        self.create_ai_inbound()
        self.client.force_login(self.head)

        response = self.client.get(reverse("inbound_requests"))

        self.assertContains(response, "AI-анализ")
        self.assertContains(response, "Кредит на Chery Tiggo")
        self.assertContains(response, "Кредит · Высокая")
        self.assertContains(response, "Spam")
        self.assertContains(response, "12%")
        self.assertContains(response, "Toxicity")
        self.assertContains(response, "8%")
        self.assertContains(response, "Troll")
        self.assertContains(response, "3%")
        self.assertContains(response, "Off-topic")
        self.assertContains(response, "2%")
        self.assertContains(response, "toxicity")
        self.assertContains(response, "Клиент хочет Chery Tiggo в кредит.")

    def test_head_request_card_shows_risk_messages_and_processing_timeline(self):
        inbound = self.create_ai_inbound()
        inbound.raw_payload_json = {
            "user_id": "777",
            "message_id": "1",
            "text": "Интересует Chery Tiggo в кредит",
            "follow_up_messages": [
                {"user_id": "777", "message_id": "2", "text": "А можно без первого взноса?"},
            ],
        }
        inbound.risk_score_rules = 40
        inbound.risk_score_final = 72
        inbound.spam_reason = "частые заявки с телефона, AI: toxicity"
        inbound.status = InboundRequestStatus.SUSPICIOUS
        deal = create_deal(client=self.client1, title="Кредит Chery", manager=self.manager1, user=self.head, inbound_request_id=inbound.pk)
        inbound.linked_client = self.client1
        inbound.linked_deal = deal
        inbound.save(
            update_fields=[
                "raw_payload_json",
                "risk_score_rules",
                "risk_score_final",
                "spam_reason",
                "status",
                "linked_client",
                "linked_deal",
            ]
        )
        channel = Channel.objects.create(type=ChannelType.TELEGRAM, name="Telegram")
        dialog = Dialog.objects.create(channel=channel, client=self.client1, deal=deal, external_thread_id="777")
        Message.objects.create(
            dialog=dialog,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            text="Интересует Chery Tiggo в кредит",
            external_message_id="1",
        )
        Message.objects.create(
            dialog=dialog,
            direction=MessageDirection.OUTBOUND,
            status=MessageStatus.SENT,
            text="Уточните желаемый первый взнос.",
            sent_by=self.manager1,
        )
        ProcessingLog.objects.create(
            inbound_request=inbound,
            step="rules_risk_scored",
            status=inbound.status,
            message="частые заявки с телефона",
        )
        ProcessingLog.objects.create(
            inbound_request=inbound,
            step="ai_analyzed",
            status=inbound.status,
            message="AI: toxicity",
        )
        self.client.force_login(self.head)

        response = self.client.get(reverse("inbound_requests"))

        self.assertContains(response, "Риск-панель заявки")
        self.assertContains(response, "72")
        self.assertContains(response, "rules: 40/100")
        self.assertContains(response, "частые заявки с телефона, AI: toxicity")
        self.assertContains(response, "А можно без первого взноса?")
        self.assertContains(response, "Уточните желаемый первый взнос.")
        self.assertContains(response, "rules_risk_scored")
        self.assertContains(response, "ai_analyzed")

    def test_head_filters_and_searches_request_cards(self):
        processed = self.create_ai_inbound()
        suspicious = self.create_ai_inbound()
        suspicious.external_id = "suspicious-card"
        suspicious.ai_topic = "Подозрительная заявка"
        suspicious.phone_raw = "+7 999 444-44-44"
        suspicious.status = InboundRequestStatus.SUSPICIOUS
        suspicious.save(update_fields=["external_id", "ai_topic", "phone_raw", "status"])
        failed = self.create_ai_inbound()
        failed.external_id = "failed-card"
        failed.ai_topic = "Ошибка обработки"
        failed.status = InboundRequestStatus.FAILED
        failed.save(update_fields=["external_id", "ai_topic", "status"])
        self.client.force_login(self.head)

        response = self.client.get(reverse("inbound_requests"), {"status": "suspicious"})
        self.assertContains(response, "Подозрительная заявка")
        self.assertNotContains(response, processed.ai_topic)
        self.assertNotContains(response, "Ошибка обработки")

        response = self.client.get(reverse("inbound_requests"), {"status": "all", "q": "444-44-44"})
        self.assertContains(response, "Подозрительная заявка")
        self.assertNotContains(response, processed.ai_topic)

    def test_head_retries_failed_request_from_admin_ops(self):
        inbound = self.create_ai_inbound()
        inbound.status = InboundRequestStatus.FAILED
        inbound.retry_count = 5
        inbound.last_error = "temporary failure"
        inbound.save(update_fields=["status", "retry_count", "last_error"])
        self.client.force_login(self.head)

        response = self.client.post(reverse("inbound_request_retry", kwargs={"pk": inbound.pk}), follow=True)

        self.assertEqual(response.status_code, 200)
        inbound.refresh_from_db()
        self.assertEqual(inbound.status, InboundRequestStatus.RECEIVED)
        self.assertEqual(inbound.retry_count, 0)
        self.assertEqual(inbound.last_error, "")
        log = inbound.processing_logs.get(step="retried_manually")
        self.assertEqual(log.details_json["user_id"], self.head.pk)
        self.assertContains(response, f"Заявка #{inbound.pk} возвращена в очередь")

    def test_head_inbound_requests_page_shows_processing_log_details(self):
        inbound = self.create_ai_inbound()
        ProcessingLog.objects.create(
            inbound_request=inbound,
            step="failed",
            status=InboundRequestStatus.BLOCKED,
            message="Телефон не разбирается: abc",
            details_json={"error": "Телефон не разбирается", "phone_raw": "abc", "email_raw": inbound.email_raw},
        )
        self.client.force_login(self.head)

        response = self.client.get(reverse("inbound_requests"))

        self.assertContains(response, "Телефон не разбирается: abc")
        self.assertContains(response, "phone_raw")
        self.assertContains(response, "abc")
        self.assertContains(response, "error")
        self.assertContains(response, "Телефон не разбирается")

    def test_head_inbound_requests_page_shows_delete_button_and_confirmation_modal(self):
        inbound = self.create_ai_inbound()
        self.client.force_login(self.head)

        response = self.client.get(reverse("inbound_requests"))

        self.assertContains(response, "Удалить")
        self.assertContains(response, f'data-bs-target="#deleteRequestModal{inbound.pk}"')
        self.assertContains(response, f'id="deleteRequestModal{inbound.pk}"')
        self.assertContains(response, "Удалить заявку?")
        self.assertContains(response, "Да, удалить")
        self.assertContains(response, reverse("inbound_request_delete", kwargs={"pk": inbound.pk}))

    def test_head_deletes_inbound_request_without_deleting_linked_deal(self):
        inbound = self.create_ai_inbound()
        deal = create_deal(client=self.client1, title="Inbound Deal", manager=self.manager1, user=self.head, inbound_request_id=inbound.id)
        inbound.linked_client = self.client1
        inbound.linked_deal = deal
        inbound.save(update_fields=["linked_client", "linked_deal"])
        self.client.force_login(self.head)

        response = self.client.post(reverse("inbound_request_delete", kwargs={"pk": inbound.pk}), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(InboundRequest.objects.filter(pk=inbound.pk).exists())
        deal.refresh_from_db()
        self.assertIsNone(deal.inbound_request_id)
        self.assertContains(response, f"Заявка #{inbound.pk} удалена. Связанная сделка сохранена.")

    def test_head_restores_blocked_request_from_spam_and_blocklist(self):
        inbound = self.create_ai_inbound()
        inbound.status = InboundRequestStatus.BLOCKED
        inbound.save(update_fields=["status"])
        Blocklist.objects.create(
            kind=BlocklistKind.PHONE,
            value=inbound.phone_normalized,
            reason="manual spam",
            added_by=self.head,
        )
        self.client.force_login(self.head)

        response = self.client.post(reverse("inbound_request_not_spam", kwargs={"pk": inbound.pk}), follow=True)

        self.assertEqual(response.status_code, 200)
        inbound.refresh_from_db()
        self.assertEqual(inbound.status, InboundRequestStatus.PROCESSED)
        self.assertIsNotNone(inbound.linked_deal_id)
        self.assertFalse(Blocklist.objects.filter(kind=BlocklistKind.PHONE, value=inbound.phone_normalized).exists())
        self.assertContains(response, "Заявка восстановлена, blocklist-сигналы сняты")

    @staticmethod
    def create_ai_inbound() -> InboundRequest:
        payload = {"phone": "+7 999 111-11-11", "text": "Интересует Chery Tiggo в кредит"}
        return InboundRequest.objects.create(
            external_id="ai-ui-1",
            source_type="telegram",
            source_name="Telegram",
            name_raw="Client One",
            phone_raw="+7 999 111-11-11",
            phone_normalized="+79991111111",
            message_text="Интересует Chery Tiggo в кредит",
            raw_payload_json=payload,
            payload_hash=payload_hash(payload),
            status=InboundRequestStatus.PROCESSED,
            ai_topic="Кредит на Chery Tiggo",
            ai_need="Рассчитать кредит и наличие автомобиля",
            ai_urgency="high",
            ai_category="credit",
            ai_spam_probability=0.12,
            ai_toxicity=0.08,
            ai_troll_probability=0.03,
            ai_off_topic_probability=0.02,
            ai_moderation_labels=["toxicity"],
            ai_summary="Клиент хочет Chery Tiggo в кредит.",
            ai_suggested_reply="Здравствуйте! Рассчитаем кредит и подскажем наличие.",
            ai_suggested_department="finance",
        )
