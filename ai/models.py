"""Database-backed AI provider settings."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class AIProviderChoices(models.TextChoices):
    """Supported AI providers."""

    OLLAMA = "ollama", "Ollama"
    OPENAI = "openai", "OpenAI"


class AIConnectionTypeChoices(models.TextChoices):
    """Human-facing AI connection types for the settings UI."""

    OLLAMA = "ollama", "Ollama (локально)"
    OPENAI_OFFICIAL = "openai_official", "OpenAI official"
    OPENAI_COMPATIBLE = "openai_compatible", "OpenAI-compatible (custom / bridge / proxy)"


class AIAPIStyleChoices(models.TextChoices):
    """Provider API style used by OpenAI-compatible endpoints."""

    OLLAMA = "ollama", "Ollama"
    CHAT_COMPLETIONS = "chat_completions", "Chat Completions"
    RESPONSES = "responses", "Responses"


class AIConnectionStatusChoices(models.TextChoices):
    """Last saved connection check result."""

    UNKNOWN = "unknown", "unknown"
    OK = "ok", "ok"
    FAIL = "fail", "fail"


class AISettings(models.Model):
    """One AI connection controlled by head users from CRM UI."""

    name = models.CharField(max_length=120, default="Ollama локально")
    is_default = models.BooleanField(default=False)
    provider = models.CharField(max_length=16, choices=AIProviderChoices.choices, default=AIProviderChoices.OLLAMA)
    connection_type = models.CharField(max_length=32, choices=AIConnectionTypeChoices.choices, default=AIConnectionTypeChoices.OLLAMA)
    ollama_url = models.URLField(default="http://127.0.0.1:11434")
    ollama_model = models.CharField(max_length=120, default="qwen3.5:9b")
    openai_base_url = models.URLField(default="https://api.openai.com/v1")
    openai_model = models.CharField(max_length=120, default="gpt-5.6-sol")
    openai_api_style = models.CharField(max_length=32, choices=AIAPIStyleChoices.choices, default=AIAPIStyleChoices.CHAT_COMPLETIONS)
    openai_transcription_model = models.CharField(max_length=120, default="gpt-transcribe")
    openai_api_key = models.TextField(blank=True)
    last_check_status = models.CharField(max_length=16, choices=AIConnectionStatusChoices.choices, default=AIConnectionStatusChoices.UNKNOWN)
    last_check_message = models.CharField(max_length=500, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="updated_ai_settings")
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "AI settings"
        verbose_name_plural = "AI settings"
        constraints = [
            models.UniqueConstraint(fields=["is_default"], condition=Q(is_default=True), name="ai_one_default_connection"),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def has_openai_api_key(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def active_base_url(self) -> str:
        if self.provider == AIProviderChoices.OLLAMA:
            return self.ollama_url
        return self.openai_base_url

    @property
    def active_model(self) -> str:
        if self.provider == AIProviderChoices.OLLAMA:
            return self.ollama_model
        return self.openai_model

    @property
    def active_api_style(self) -> str:
        if self.provider == AIProviderChoices.OLLAMA:
            return AIAPIStyleChoices.OLLAMA
        return self.openai_api_style

    @property
    def active_key_mask(self) -> str:
        if self.provider == AIProviderChoices.OLLAMA or not self.openai_api_key:
            return ""
        tail = self.openai_api_key[-4:] if len(self.openai_api_key) >= 4 else "****"
        return f"***{tail}"

    def save(self, *args, **kwargs):
        if self.is_default:
            type(self).objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)

    def make_default(self) -> None:
        """Mark this connection as the runtime default."""

        self.is_default = True
        self.save(update_fields=["is_default", "updated_at"])

    @classmethod
    def current(cls) -> "AISettings":
        """Return the default connection, creating one from env defaults if needed."""

        current = cls.objects.filter(is_default=True).order_by("pk").first()
        if current:
            return current

        current = cls.objects.order_by("pk").first()
        if current:
            current.make_default()
            return current

        return cls.objects.create(**cls.default_connection_values(), is_default=True)

    @classmethod
    def default_connection_values(cls) -> dict:
        """Build initial connection values from env fallback."""

        connection_type = cls.connection_type_from_env()
        provider = AIProviderChoices.OPENAI if connection_type != AIConnectionTypeChoices.OLLAMA else AIProviderChoices.OLLAMA
        return {
            "name": cls.default_connection_name(connection_type),
            "provider": provider,
            "connection_type": connection_type,
            "ollama_url": settings.OLLAMA_URL,
            "ollama_model": settings.OLLAMA_MODEL,
            "openai_base_url": settings.OPENAI_BASE_URL,
            "openai_model": settings.OPENAI_MODEL,
            "openai_api_style": AIAPIStyleChoices.CHAT_COMPLETIONS,
            "openai_transcription_model": settings.OPENAI_TRANSCRIPTION_MODEL,
            "openai_api_key": settings.OPENAI_API_KEY or "",
        }

    @classmethod
    def default_connection_name(cls, connection_type: str) -> str:
        """Return a readable name for an initial connection."""

        if connection_type == AIConnectionTypeChoices.OPENAI_OFFICIAL:
            return "OpenAI official"
        if connection_type == AIConnectionTypeChoices.OPENAI_COMPATIBLE:
            return "Custom OpenAI bridge"
        return "Ollama локально"

    @classmethod
    def connection_type_from_env(cls) -> str:
        """Infer the first settings UI type from env fallback values."""

        if settings.AI_PROVIDER != AIProviderChoices.OPENAI:
            return AIConnectionTypeChoices.OLLAMA
        if settings.OPENAI_BASE_URL.rstrip("/") == "https://api.openai.com/v1":
            return AIConnectionTypeChoices.OPENAI_OFFICIAL
        return AIConnectionTypeChoices.OPENAI_COMPATIBLE
