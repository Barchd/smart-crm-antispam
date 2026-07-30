"""Seed demo CRM users."""

from __future__ import annotations

import os
import secrets

from django.core.management.base import BaseCommand

from crm.models import RoleChoices, User


class Command(BaseCommand):
    help = "Create one head and two manager users for the CRM MVP."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Print generated passwords without saving users.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        seeds = [
            ("head", "CRM_HEAD_PASSWORD", "Head User", RoleChoices.HEAD),
            ("manager1", "CRM_MANAGER1_PASSWORD", "Manager One", RoleChoices.MANAGER),
            ("manager2", "CRM_MANAGER2_PASSWORD", "Manager Two", RoleChoices.MANAGER),
        ]

        lines = []
        for username, env_name, full_name, role in seeds:
            password = os.environ.get(env_name) or secrets.token_urlsafe(12)
            if not dry_run:
                User.objects.update_or_create(
                    username=username,
                    defaults={
                        "full_name": full_name,
                        "role": role,
                        "is_active": True,
                        "is_staff": role == RoleChoices.HEAD,
                        "is_superuser": role == RoleChoices.HEAD,
                    },
                )
                user = User.objects.get(username=username)
                user.set_password(password)
                user.save(update_fields=["password", "full_name", "role", "is_active", "is_staff", "is_superuser"])
            lines.append(f"{username}: {password}" if not os.environ.get(env_name) else f"{username}: password taken from env {env_name}")

        self.stdout.write(self.style.SUCCESS("Seeded CRM users:"))
        for line in lines:
            self.stdout.write(f"- {line}")


