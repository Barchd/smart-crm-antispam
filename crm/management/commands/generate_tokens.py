"""Generate local secret values for .env."""

from __future__ import annotations

import secrets

from django.core.management.base import BaseCommand
from django.core.management.utils import get_random_secret_key


class Command(BaseCommand):
    help = "Print generated secret values for local .env without writing files."

    def handle(self, *args, **options):
        values = {
            "DJANGO_SECRET_KEY": get_random_secret_key(),
            "WEBHOOK_SECRET": secrets.token_urlsafe(32),
            "ADMIN_API_TOKEN": secrets.token_urlsafe(32),
        }
        self.stdout.write("# Copy these values to your local .env. Do not commit .env.")
        for name, value in values.items():
            self.stdout.write(f"{name}={value}")
