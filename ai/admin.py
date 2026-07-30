"""Django admin registration for AI settings."""

from __future__ import annotations

from django.contrib import admin

from .models import AISettings


@admin.register(AISettings)
class AISettingsAdmin(admin.ModelAdmin):
    """Inspect AI settings without exposing secrets in list views."""

    list_display = (
        "name",
        "connection_type",
        "is_default",
        "provider",
        "openai_api_style",
        "ollama_model",
        "openai_model",
        "has_openai_api_key",
        "last_check_status",
        "updated_by",
        "updated_at",
    )
    readonly_fields = ("has_openai_api_key", "last_check_status", "last_check_message", "last_checked_at", "updated_at")
    fields = (
        "name",
        "is_default",
        "connection_type",
        "provider",
        "ollama_url",
        "ollama_model",
        "openai_base_url",
        "openai_model",
        "openai_api_style",
        "openai_transcription_model",
        "has_openai_api_key",
        "last_check_status",
        "last_check_message",
        "last_checked_at",
        "updated_by",
        "updated_at",
    )
