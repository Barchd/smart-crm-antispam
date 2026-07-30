from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from crm.models import Client, DealStage, RoleChoices
from crm.phones import normalize_phone
from crm.services import create_deal
from intake.models import InboundRequest, InboundRequestStatus
from intake.services import payload_hash


@override_settings(ADMIN_API_TOKEN="admin-token")
class PermissionTests(TestCase):
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
        self.client1 = Client.objects.create(
            name="Client One",
            phone_raw="+7 999 111-11-11",
            phone_normalized=normalize_phone("+7 999 111-11-11"),
            manager=self.manager1,
        )
        self.client2 = Client.objects.create(
            name="Client Two",
            phone_raw="+7 999 222-22-22",
            phone_normalized=normalize_phone("+7 999 222-22-22"),
            manager=self.manager2,
        )
        self.deal1 = create_deal(client=self.client1, title="Deal One", manager=self.manager1, user=self.head)
        self.deal2 = create_deal(client=self.client2, title="Deal Two", manager=self.manager2, user=self.head)

    def test_manager_sees_only_own_deals_in_list(self):
        self.client.force_login(self.manager1)
        response = self.client.get(reverse("deals"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Deal One")
        self.assertNotContains(response, "Deal Two")

    def test_manager_gets_404_for_foreign_deal_url(self):
        self.client.force_login(self.manager1)
        response = self.client.get(reverse("deal_detail", kwargs={"pk": self.deal2.pk}))
        self.assertEqual(response.status_code, 404)

    def test_manager_gets_404_for_foreign_deal_api(self):
        self.client.force_login(self.manager1)
        response = self.client.get(f"/api/v1/deals/{self.deal2.pk}")
        self.assertEqual(response.status_code, 404)

    def test_manager_cannot_change_responsible(self):
        self.client.force_login(self.manager1)
        response = self.client.post(
            reverse("deal_detail", kwargs={"pk": self.deal1.pk}),
            {
                "title": self.deal1.title,
                "amount": str(self.deal1.amount),
                "manager": self.manager2.pk,
                "next_contact_at": "",
                "reply_draft": "Ответ",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.deal1.refresh_from_db()
        self.assertEqual(self.deal1.manager, self.manager1)
        self.assertEqual(self.deal1.stage, DealStage.NEW)

    def test_manager_cannot_open_inbound_requests_page(self):
        self.client.force_login(self.manager1)
        response = self.client.get(reverse("inbound_requests"))
        self.assertEqual(response.status_code, 403)

    def test_manager_cannot_delete_inbound_request(self):
        payload = {"phone": "+7 999 111-11-11", "text": "Нужен кредит"}
        inbound = InboundRequest.objects.create(
            external_id="perm-delete-1",
            source_type="telegram",
            phone_raw="+7 999 111-11-11",
            phone_normalized="+79991111111",
            message_text="Нужен кредит",
            raw_payload_json=payload,
            payload_hash=payload_hash(payload),
            status=InboundRequestStatus.RECEIVED,
        )
        self.client.force_login(self.manager1)

        response = self.client.post(reverse("inbound_request_delete", kwargs={"pk": inbound.pk}))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(InboundRequest.objects.filter(pk=inbound.pk).exists())

    def test_manager_cannot_retry_inbound_request(self):
        payload = {"phone": "+7 999 111-11-11", "text": "Нужен кредит"}
        inbound = InboundRequest.objects.create(
            external_id="perm-retry-1",
            source_type="telegram",
            phone_raw="+7 999 111-11-11",
            phone_normalized="+79991111111",
            message_text="Нужен кредит",
            raw_payload_json=payload,
            payload_hash=payload_hash(payload),
            status=InboundRequestStatus.FAILED,
        )
        self.client.force_login(self.manager1)

        response = self.client.post(reverse("inbound_request_retry", kwargs={"pk": inbound.pk}))

        self.assertEqual(response.status_code, 403)
        inbound.refresh_from_db()
        self.assertEqual(inbound.status, InboundRequestStatus.FAILED)

    def test_get_inbound_request_delete_is_forbidden(self):
        payload = {"phone": "+7 999 111-11-11", "text": "Нужен кредит"}
        inbound = InboundRequest.objects.create(
            external_id="perm-delete-2",
            source_type="telegram",
            phone_raw="+7 999 111-11-11",
            phone_normalized="+79991111111",
            message_text="Нужен кредит",
            raw_payload_json=payload,
            payload_hash=payload_hash(payload),
            status=InboundRequestStatus.RECEIVED,
        )
        self.client.force_login(self.head)

        response = self.client.get(reverse("inbound_request_delete", kwargs={"pk": inbound.pk}))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(InboundRequest.objects.filter(pk=inbound.pk).exists())

    def test_admin_api_without_role_or_token_returns_403(self):
        response = self.client.get("/api/v1/admin/requests/recent")
        self.assertEqual(response.status_code, 403)

    def test_head_can_open_everything_and_admin_api(self):
        self.client.force_login(self.head)
        self.assertEqual(self.client.get(reverse("deal_detail", kwargs={"pk": self.deal2.pk})).status_code, 200)
        self.assertEqual(self.client.get(reverse("inbound_requests")).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/admin/requests/recent").status_code, 200)

    def test_admin_token_allows_admin_api(self):
        response = self.client.get("/api/v1/admin/requests/recent", headers={"X-Admin-Token": "admin-token"})
        self.assertEqual(response.status_code, 200)
