from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from crm.models import RoleChoices


class NavigationTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.head = user_model.objects.create_user(username="head", password="secret", full_name="Head", role=RoleChoices.HEAD)
        self.manager = user_model.objects.create_user(username="manager", password="secret", full_name="Manager", role=RoleChoices.MANAGER)

    def test_head_navigation_has_settings_dropdown(self):
        self.client.force_login(self.head)

        response = self.client.get(reverse("deals"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сделки")
        self.assertContains(response, "Клиенты")
        self.assertContains(response, "Заявки")
        self.assertContains(response, "Настройки")
        self.assertContains(response, reverse("users"))
        self.assertContains(response, reverse("ai_settings"))
        self.assertContains(response, reverse("bot_settings"))

    def test_manager_navigation_hides_head_settings(self):
        self.client.force_login(self.manager)

        response = self.client.get(reverse("deals"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сделки")
        self.assertContains(response, "Клиенты")
        self.assertContains(response, "Пароль")
        self.assertNotContains(response, "Заявки")
        self.assertNotContains(response, "Настройки")
        self.assertNotContains(response, reverse("users"))
        self.assertNotContains(response, reverse("ai_settings"))
        self.assertNotContains(response, reverse("bot_settings"))

    def test_settings_pages_have_local_subnav(self):
        self.client.force_login(self.head)

        for url_name in ("users", "ai_settings", "bot_settings"):
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Администрирование")
                self.assertContains(response, "Настройки")
                self.assertContains(response, reverse("users"))
                self.assertContains(response, reverse("ai_settings"))
                self.assertContains(response, reverse("bot_settings"))
