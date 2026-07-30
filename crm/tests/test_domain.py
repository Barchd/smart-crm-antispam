from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from crm.models import Client, DealLog, DealLogAction, DealStage, RoleChoices
from crm.phones import normalize_phone
from crm.services import change_deal_manager, change_deal_stage, choose_responsible_manager, create_deal


class PhoneNormalizationTests(TestCase):
    def test_russian_phone_formats_normalize_to_same_e164(self):
        expected = "+79991234567"
        self.assertEqual(normalize_phone("+7 999 123-45-67"), expected)
        self.assertEqual(normalize_phone("8 (999) 123-45-67"), expected)
        self.assertEqual(normalize_phone("79991234567"), expected)


class DealDomainTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.head = user_model.objects.create_user(
            username="head",
            password="secret",
            full_name="Head",
            role=RoleChoices.HEAD,
        )
        self.manager1 = user_model.objects.create_user(
            username="manager1",
            password="secret",
            full_name="Manager One",
            role=RoleChoices.MANAGER,
        )
        self.manager2 = user_model.objects.create_user(
            username="manager2",
            password="secret",
            full_name="Manager Two",
            role=RoleChoices.MANAGER,
        )
        self.client = Client.objects.create(
            name="Иван Петров",
            phone_raw="8 (999) 123-45-67",
            phone_normalized=normalize_phone("8 (999) 123-45-67"),
            email="ivan@example.test",
            source="site",
            manager=self.manager1,
            comment="Первичный интерес",
        )

    def test_create_deal_writes_created_log(self):
        deal = create_deal(
            client=self.client,
            title="Покупка Haval",
            amount=Decimal("2500000.00"),
            user=self.head,
        )

        self.assertEqual(deal.manager, self.manager1)
        self.assertEqual(deal.stage, DealStage.NEW)
        self.assertEqual(deal.logs.count(), 2)
        actions = list(deal.logs.order_by("created_at", "id").values_list("action", flat=True))
        self.assertEqual(actions, [DealLogAction.DEAL_CREATED, DealLogAction.MANAGER_CHANGED])
        created_log = deal.logs.get(action=DealLogAction.DEAL_CREATED)
        assigned_log = deal.logs.get(action=DealLogAction.MANAGER_CHANGED, old_value="")
        self.assertEqual(created_log.new_value, str(self.manager1.id))
        self.assertEqual(assigned_log.new_value, str(self.manager1.id))

    def test_stage_and_manager_changes_write_logs(self):
        deal = create_deal(client=self.client, title="Покупка Chery", user=self.head)

        change_deal_stage(deal=deal, new_stage=DealStage.FIRST_CONTACT, user=self.manager1)
        change_deal_manager(deal=deal, new_manager=self.manager2, user=self.head)

        actions = list(DealLog.objects.filter(deal=deal).order_by("created_at", "id").values_list("action", flat=True))
        self.assertEqual(
            actions,
            [
                DealLogAction.DEAL_CREATED,
                DealLogAction.MANAGER_CHANGED,
                DealLogAction.STAGE_CHANGED,
                DealLogAction.MANAGER_CHANGED,
            ],
        )
        deal.refresh_from_db()
        self.assertEqual(deal.stage, DealStage.FIRST_CONTACT)
        self.assertEqual(deal.manager, self.manager2)

    def test_created_log_summary_falls_back_to_deal_manager_when_new_value_is_empty(self):
        deal = create_deal(client=self.client, title="Fallback Summary", manager=self.manager1, user=self.head)
        created_log = deal.logs.get(action=DealLogAction.DEAL_CREATED)
        created_log.new_value = ""
        created_log.save(update_fields=["new_value"])

        created_log.refresh_from_db()
        self.assertEqual(created_log.change_summary, "Сделка создана · ответственный: Manager One")

    def test_new_to_first_contact_is_allowed(self):
        deal = create_deal(client=self.client, title="Первичный контакт", user=self.head)

        change_deal_stage(deal=deal, new_stage=DealStage.FIRST_CONTACT, user=self.manager1)

        deal.refresh_from_db()
        self.assertEqual(deal.stage, DealStage.FIRST_CONTACT)
        self.assertEqual(deal.logs.filter(action=DealLogAction.STAGE_CHANGED).count(), 1)

    def test_new_to_qualification_is_rejected_without_log(self):
        deal = create_deal(client=self.client, title="Нельзя перескочить", user=self.head)

        with self.assertRaises(ValidationError):
            change_deal_stage(deal=deal, new_stage=DealStage.QUALIFICATION, user=self.manager1)

        deal.refresh_from_db()
        self.assertEqual(deal.stage, DealStage.NEW)
        self.assertFalse(deal.logs.filter(action=DealLogAction.STAGE_CHANGED).exists())

    def test_negotiation_to_won_is_allowed(self):
        deal = create_deal(client=self.client, title="Успешная сделка", user=self.head)
        deal.stage = DealStage.NEGOTIATION
        deal.save(update_fields=["stage"])

        change_deal_stage(deal=deal, new_stage=DealStage.WON, user=self.manager1)

        deal.refresh_from_db()
        self.assertEqual(deal.stage, DealStage.WON)
        self.assertTrue(deal.logs.filter(action=DealLogAction.STAGE_CHANGED, old_value=DealStage.NEGOTIATION, new_value=DealStage.WON).exists())

    def test_qualification_to_won_is_rejected(self):
        deal = create_deal(client=self.client, title="Рано закрывать", user=self.head)
        deal.stage = DealStage.QUALIFICATION
        deal.save(update_fields=["stage"])

        with self.assertRaises(ValidationError):
            change_deal_stage(deal=deal, new_stage=DealStage.WON, user=self.manager1)

        deal.refresh_from_db()
        self.assertEqual(deal.stage, DealStage.QUALIFICATION)
        self.assertFalse(deal.logs.filter(action=DealLogAction.STAGE_CHANGED).exists())

    def test_new_to_lost_is_allowed(self):
        deal = create_deal(client=self.client, title="Отказ клиента", user=self.head)

        change_deal_stage(deal=deal, new_stage=DealStage.LOST, user=self.manager1)

        deal.refresh_from_db()
        self.assertEqual(deal.stage, DealStage.LOST)

    def test_terminal_stage_rejects_any_transition(self):
        deal = create_deal(client=self.client, title="Закрытая сделка", user=self.head)
        deal.stage = DealStage.WON
        deal.save(update_fields=["stage"])

        with self.assertRaisesMessage(ValidationError, "Сделка закрыта"):
            change_deal_stage(deal=deal, new_stage=DealStage.LOST, user=self.manager1)

        deal.refresh_from_db()
        self.assertEqual(deal.stage, DealStage.WON)
        self.assertFalse(deal.logs.filter(action=DealLogAction.STAGE_CHANGED).exists())

    def test_new_client_assignment_chooses_manager_with_less_open_deals(self):
        create_deal(client=self.client, title="Открытая сделка", manager=self.manager1, user=self.head)

        new_client = Client.objects.create(
            name="Петр Сидоров",
            phone_raw="+7 999 000-00-00",
            phone_normalized=normalize_phone("+7 999 000-00-00"),
            manager=self.manager2,
        )

        self.assertEqual(choose_responsible_manager(), self.manager2)
        self.assertEqual(choose_responsible_manager(client=new_client), self.manager2)
