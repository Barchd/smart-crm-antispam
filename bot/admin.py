"""Django admin registration for Telegram bot settings."""

from __future__ import annotations

from django.contrib import admin

from .models import BotSettings


@admin.register(BotSettings)
class BotSettingsAdmin(admin.ModelAdmin):
    """Inspect bot settings without exposing the Telegram token."""

    list_display = ("has_bot_token", "has_customer_prompt", "admin_chat_id", "updated_by", "updated_at")
    readonly_fields = ("has_bot_token", "updated_at")
    fields = ("has_bot_token", "admin_chat_id", "admin_telegram_ids", "customer_prompt", "updated_by", "updated_at")

    @admin.display(boolean=True, description="Customer prompt")
    def has_customer_prompt(self, obj: BotSettings) -> bool:
        return bool(obj.customer_prompt.strip())
