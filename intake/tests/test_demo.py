from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from crm.models import Client, Deal
from intake.models import InboundRequest, InboundRequestStatus


class DemoDataTests(TestCase):
    def test_seed_demo_creates_clients_and_deals(self):
        out = StringIO()

        call_command("seed_demo", stdout=out)

        self.assertGreaterEqual(Client.objects.count(), 4)
        self.assertGreaterEqual(Deal.objects.count(), 6)
        self.assertIn("Demo clients", out.getvalue())

    @override_settings(WEBHOOK_SECRET="demo-secret", ALLOWED_HOSTS=["127.0.0.1", "testserver"])
    def test_send_demo_leads_uses_real_endpoints(self):
        out = StringIO()

        call_command("send_demo_leads", stdout=out)

        self.assertEqual(InboundRequest.objects.count(), 12)
        self.assertTrue(InboundRequest.objects.filter(status=InboundRequestStatus.DUPLICATE).exists())
        self.assertTrue(InboundRequest.objects.filter(status=InboundRequestStatus.BLOCKED, spam_reason="honeypot").exists())
        self.assertTrue(InboundRequest.objects.filter(phone_raw="+7 999 700-00-00").exists())
        self.assertIn("Sent demo leads: 12", out.getvalue())

