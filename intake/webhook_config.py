"""Runtime helper for the HMAC webhook secret: DB first, env fallback."""

from __future__ import annotations

from django.conf import settings
from django.db import OperationalError, ProgrammingError

from .models import WebhookSettings


def get_webhook_secret() -> str:
    """Return the active HMAC secret.

    Priority: WebhookSettings DB row → settings.WEBHOOK_SECRET env.
    Falls back to env when migrations haven't run yet (startup or test isolation).
    """
    try:
        db_secret = WebhookSettings.current().webhook_secret
        if db_secret:
            return db_secret
    except (OperationalError, ProgrammingError):
        pass
    return settings.WEBHOOK_SECRET or ""
