from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from crm.models import Client, RoleChoices
from crm.phones import normalize_phone


class UserManagementTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.head = user_model.objects.create_user(username="head", password="head-pass-123", full_name="Head", role=RoleChoices.HEAD)
        self.manager = user_model.objects.create_user(username="manager", password="manager-pass-123", full_name="Manager", role=RoleChoices.MANAGER)

    def test_manager_cannot_open_user_management(self):
        self.client.force_login(self.manager)

        self.assertEqual(self.client.get(reverse("users")).status_code, 403)
        self.assertEqual(self.client.get(reverse("user_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("user_delete", kwargs={"pk": self.head.pk})).status_code, 403)

    def test_head_creates_user_and_assigns_role(self):
        self.client.force_login(self.head)

        response = self.client.post(
            reverse("user_create"),
            {
                "username": "new-manager",
                "full_name": "New Manager",
                "role": RoleChoices.MANAGER,
                "is_active": "on",
                "password1": "strong-pass-12345",
                "password2": "strong-pass-12345",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        user = get_user_model().objects.get(username="new-manager")
        self.assertEqual(user.role, RoleChoices.MANAGER)
        self.assertTrue(user.check_password("strong-pass-12345"))
        self.assertFalse(user.is_staff)

    def test_head_updates_user_role(self):
        self.client.force_login(self.head)

        response = self.client.post(
            reverse("user_edit", kwargs={"pk": self.manager.pk}),
            {
                "username": "manager",
                "full_name": "Promoted Manager",
                "role": RoleChoices.HEAD,
                "is_active": "on",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.role, RoleChoices.HEAD)
        self.assertTrue(self.manager.is_staff)
        self.assertTrue(self.manager.is_superuser)
        self.assertTrue(self.manager.check_password("manager-pass-123"))

    def test_head_sets_user_password_on_edit(self):
        self.client.force_login(self.head)

        response = self.client.post(
            reverse("user_edit", kwargs={"pk": self.manager.pk}),
            {
                "username": "manager",
                "full_name": "Manager",
                "role": RoleChoices.MANAGER,
                "is_active": "on",
                "password1": "new-admin-set-pass-12345",
                "password2": "new-admin-set-pass-12345",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.manager.refresh_from_db()
        self.assertFalse(self.manager.check_password("manager-pass-123"))
        self.assertTrue(self.manager.check_password("new-admin-set-pass-12345"))
        self.assertNotContains(response, "new-admin-set-pass-12345")

    def test_head_user_forms_include_password_generator(self):
        self.client.force_login(self.head)

        create_response = self.client.get(reverse("user_create"))
        edit_response = self.client.get(reverse("user_edit", kwargs={"pk": self.manager.pk}))

        for response in (create_response, edit_response):
            self.assertContains(response, "Генератор пароля")
            self.assertContains(response, "Сгенерировать")
            self.assertContains(response, "Скопировать")
            self.assertContains(response, "id_password1")
            self.assertContains(response, "id_password2")

    def test_head_deletes_unreferenced_user(self):
        user_model = get_user_model()
        deleted_user = user_model.objects.create_user(
            username="unused-manager",
            password="unused-pass-123",
            full_name="Unused Manager",
            role=RoleChoices.MANAGER,
        )
        self.client.force_login(self.head)

        response = self.client.post(reverse("user_delete", kwargs={"pk": deleted_user.pk}), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(user_model.objects.filter(pk=deleted_user.pk).exists())
        self.assertContains(response, "Пользователь unused-manager удален")

    def test_head_cannot_delete_self(self):
        self.client.force_login(self.head)

        response = self.client.post(reverse("user_delete", kwargs={"pk": self.head.pk}), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(get_user_model().objects.filter(pk=self.head.pk).exists())
        self.assertContains(response, "Нельзя удалить самого себя")

    def test_head_cannot_delete_user_with_protected_history(self):
        Client.objects.create(
            name="Protected Client",
            phone_raw="+7 999 555-55-55",
            phone_normalized=normalize_phone("+7 999 555-55-55"),
            manager=self.manager,
        )
        self.client.force_login(self.head)

        response = self.client.post(reverse("user_delete", kwargs={"pk": self.manager.pk}), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(get_user_model().objects.filter(pk=self.manager.pk).exists())
        self.assertContains(response, "Отключите его через поле Активен")

    def test_user_can_change_own_password(self):
        self.client.force_login(self.manager)

        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": "manager-pass-123",
                "new_password1": "new-manager-pass-12345",
                "new_password2": "new-manager-pass-12345",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Пароль изменен")
        self.manager.refresh_from_db()
        self.assertFalse(self.manager.check_password("manager-pass-123"))
        self.assertTrue(self.manager.check_password("new-manager-pass-12345"))
