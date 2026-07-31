from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from crm.models import LoginAttempt, LoginAttemptResult, RoleChoices


class AuthFlowTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.head = self.User.objects.create_user(
            username="head",
            password="head-pass-123",
            full_name="Head User",
            role=RoleChoices.HEAD,
            is_staff=True,
        )
        self.manager = self.User.objects.create_user(
            username="manager1",
            password="manager-pass-123",
            full_name="Manager One",
            role=RoleChoices.MANAGER,
        )

    def test_login_required_redirects_to_login(self):
        response = self.client.get(reverse("deals"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_head_login_and_logout(self):
        response = self.client.post(
            reverse("login"),
            {"username": "head", "password": "head-pass-123"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Head User")
        self.assertContains(response, "Роль: head")

        response = self.client.post(reverse("logout"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Вход в CRM")

    def test_correct_password_bypasses_previous_failed_attempts_and_resets_active_series(self):
        for _ in range(5):
            response = self.client.post(
                reverse("login"),
                {"username": "manager1", "password": "wrong-password"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Пожалуйста, введите правильные")

        response = self.client.post(
            reverse("login"),
            {"username": "manager1", "password": "manager-pass-123"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Manager One")
        self.assertEqual(LoginAttempt.failure_count("manager1", ip_address="127.0.0.1"), 0)

    def test_login_throttle_blocks_sixth_bad_password_from_same_ip(self):
        for _ in range(5):
            self.client.post(reverse("login"), {"username": "manager1", "password": "wrong-password"})

        response = self.client.post(reverse("login"), {"username": "manager1", "password": "wrong-password"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Слишком много неудачных попыток")
        self.assertFalse(self.client.session.get("_auth_user_id"))

        failed_count = LoginAttempt.objects.filter(
            username=LoginAttempt.normalize_username("manager1"),
            result=LoginAttemptResult.FAILED,
        ).count()
        blocked_count = LoginAttempt.objects.filter(
            username=LoginAttempt.normalize_username("manager1"),
            result=LoginAttemptResult.BLOCKED,
        ).count()
        self.assertEqual(failed_count, 5)
        self.assertEqual(blocked_count, 1)

    def test_failures_from_another_ip_do_not_lock_login(self):
        for _ in range(5):
            self.client.post(reverse("login"), {"username": "manager1", "password": "wrong-password"}, REMOTE_ADDR="198.51.100.10")

        response = self.client.post(
            reverse("login"),
            {"username": "manager1", "password": "manager-pass-123"},
            REMOTE_ADDR="198.51.100.11",
            follow=True,
        )
        self.assertContains(response, "Manager One")

    @override_settings(LOGIN_MAX_ATTEMPTS=2, LOGIN_ATTEMPT_WINDOW_MINUTES=10)
    def test_login_throttle_uses_settings(self):
        self.client.post(reverse("login"), {"username": "manager1", "password": "wrong-password"})
        self.client.post(reverse("login"), {"username": "manager1", "password": "wrong-password"})

        response = self.client.post(reverse("login"), {"username": "manager1", "password": "wrong-password"})
        self.assertContains(response, "Слишком много неудачных попыток")


class SeedUsersCommandTests(TestCase):
    def test_seed_users_command_creates_demo_accounts(self):
        user_model = get_user_model()
        with patch.dict(
            "os.environ",
            {
                "CRM_HEAD_PASSWORD": "head-secret",
                "CRM_MANAGER1_PASSWORD": "manager1-secret",
                "CRM_MANAGER2_PASSWORD": "manager2-secret",
            },
            clear=False,
        ):
            call_command("seed_users")

        users = {user.username: user for user in user_model.objects.all()}
        self.assertSetEqual(set(users), {"head", "manager1", "manager2"})
        self.assertTrue(users["head"].is_head)
        self.assertTrue(users["head"].is_staff)
        self.assertEqual(users["manager1"].role, RoleChoices.MANAGER)
        self.assertEqual(users["manager2"].role, RoleChoices.MANAGER)
