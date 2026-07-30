"""Database-backed Telegram chat-bot settings."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class BotSettings(models.Model):
    """Singleton bot settings controlled by head users from CRM UI."""

    bot_token = models.TextField(blank=True)
    admin_chat_id = models.CharField(max_length=64, blank=True)
    admin_telegram_ids = models.TextField(blank=True, help_text="Comma or newline separated numeric Telegram user ids.")
    customer_prompt = models.TextField(
        blank=True,
        max_length=4000,
        help_text="Дополнительные инструкции для AI-черновиков клиентского Telegram-бота.",
    )
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="updated_bot_settings")
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Bot settings"
        verbose_name_plural = "Bot settings"

    def __str__(self) -> str:
        return "Telegram chat-bot settings"

    @property
    def has_bot_token(self) -> bool:
        return bool(self.bot_token)

    def allowed_user_ids(self) -> set[int]:
        """Parse allowlist from chat id and comma/newline separated ids."""

        ids: set[int] = set()
        raw_values = [self.admin_chat_id]
        raw_values.extend(self.admin_telegram_ids.replace("\n", ",").split(","))
        for value in raw_values:
            value = value.strip()
            if not value:
                continue
            try:
                ids.add(int(value))
            except ValueError:
                continue
        return ids

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)

    @classmethod
    def current(cls) -> "BotSettings":
        """Return singleton settings row, creating it from env defaults if needed."""

        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "bot_token": settings.BOT_TOKEN or "",
                "admin_chat_id": settings.ADMIN_CHAT_ID or "",
                "admin_telegram_ids": ",".join(str(item) for item in settings.ADMIN_TELEGRAM_IDS),
                "customer_prompt": "",
            },
        )
        return obj
