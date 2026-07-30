"""Intake models."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


AI_URGENCY_LABELS = {
    "low": "Низкая",
    "medium": "Средняя",
    "high": "Высокая",
}

AI_CATEGORY_LABELS = {
    "purchase": "Покупка",
    "credit": "Кредит",
    "trade_in": "Trade-in",
    "service": "Сервис",
    "complaint": "Жалоба",
    "spam": "Спам",
    "other": "Другое",
}

AI_DEPARTMENT_LABELS = {
    "sales": "Продажи",
    "finance": "Финансы",
    "trade_in": "Trade-in",
    "service": "Сервис",
    "support": "Поддержка",
    "unknown": "Не определен",
}


class InboundRequestStatus(models.TextChoices):
    """Status machine for incoming requests."""

    RECEIVED = "received", "Received"
    DUPLICATE = "duplicate", "Duplicate"
    PROCESSING = "processing", "Processing"
    PROCESSED = "processed", "Processed"
    SUSPICIOUS = "suspicious", "Suspicious"
    RETRY_WAIT = "retry_wait", "Retry wait"
    FAILED = "failed", "Failed"
    BLOCKED = "blocked", "Blocked"


class TrustLevel(models.TextChoices):
    """Source trust classification set server-side after credential verification."""

    EXTERNAL = "external", "External"
    INTERNAL = "internal", "Internal"


class InboundRequest(models.Model):
    """Raw incoming request from external sources or internal form."""

    external_id = models.CharField(max_length=120, db_index=True)
    source_type = models.CharField(max_length=50, db_index=True)
    source_name = models.CharField(max_length=120, blank=True)
    name_raw = models.CharField(max_length=255, blank=True)
    phone_raw = models.CharField(max_length=64, blank=True)
    phone_normalized = models.CharField(max_length=32, blank=True, db_index=True)
    email_raw = models.EmailField(blank=True)
    message_text = models.TextField(blank=True)
    received_at = models.DateTimeField(default=timezone.now)
    raw_payload_json = models.JSONField(default=dict)
    payload_hash = models.CharField(max_length=64, db_index=True)
    headers_json = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    status = models.CharField(max_length=32, choices=InboundRequestStatus.choices, default=InboundRequestStatus.RECEIVED, db_index=True)
    duplicate_of_request = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="duplicates")
    linked_client = models.ForeignKey("crm.Client", on_delete=models.SET_NULL, null=True, blank=True, related_name="inbound_requests")
    linked_deal = models.ForeignKey("crm.Deal", on_delete=models.SET_NULL, null=True, blank=True, related_name="inbound_requests")
    ai_topic = models.CharField(max_length=120, blank=True)
    ai_need = models.TextField(blank=True)
    ai_urgency = models.CharField(max_length=50, blank=True)
    ai_category = models.CharField(max_length=50, blank=True)
    ai_spam_probability = models.FloatField(null=True, blank=True)
    ai_toxicity = models.FloatField(null=True, blank=True)
    ai_troll_probability = models.FloatField(null=True, blank=True)
    ai_off_topic_probability = models.FloatField(null=True, blank=True)
    ai_moderation_labels = models.JSONField(default=list, blank=True)
    ai_summary = models.TextField(blank=True)
    ai_suggested_reply = models.TextField(blank=True)
    ai_suggested_department = models.CharField(max_length=120, blank=True)
    ai_suggested_employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_suggested_requests")
    risk_score_rules = models.PositiveSmallIntegerField(default=0)
    risk_score_final = models.PositiveSmallIntegerField(default=0)
    spam_reason = models.TextField(blank=True)
    trust_level = models.CharField(
        max_length=16,
        choices=TrustLevel.choices,
        default=TrustLevel.EXTERNAL,
        db_index=True,
    )
    retry_count = models.PositiveSmallIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    risk_restored_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["source_type", "external_id"]),
            models.Index(fields=["status", "next_retry_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.source_type}:{self.external_id}"

    @property
    def has_ai_analysis(self) -> bool:
        """Return whether the request has meaningful AI analysis fields."""

        return any(
            [
                self.ai_topic,
                self.ai_need,
                self.ai_urgency,
                self.ai_category,
                self.ai_spam_probability is not None,
                self.ai_toxicity is not None,
                self.ai_troll_probability is not None,
                self.ai_off_topic_probability is not None,
                self.ai_moderation_labels,
                self.ai_summary,
                self.ai_suggested_reply,
                self.ai_suggested_department,
                self.ai_suggested_employee_id,
            ]
        )

    @property
    def ai_urgency_display(self) -> str:
        return AI_URGENCY_LABELS.get((self.ai_urgency or "").strip(), self.ai_urgency or "-")

    @property
    def ai_category_display(self) -> str:
        return AI_CATEGORY_LABELS.get((self.ai_category or "").strip(), self.ai_category or "-")

    @property
    def ai_department_display(self) -> str:
        return AI_DEPARTMENT_LABELS.get((self.ai_suggested_department or "").strip(), self.ai_suggested_department or "-")

    @property
    def ai_spam_percent(self) -> str:
        if self.ai_spam_probability is None:
            return "-"
        return f"{self.ai_spam_probability * 100:.0f}%"

    @property
    def ai_toxicity_percent(self) -> str:
        if self.ai_toxicity is None:
            return "-"
        return f"{self.ai_toxicity * 100:.0f}%"

    @property
    def ai_troll_percent(self) -> str:
        if self.ai_troll_probability is None:
            return "-"
        return f"{self.ai_troll_probability * 100:.0f}%"

    @property
    def ai_off_topic_percent(self) -> str:
        if self.ai_off_topic_probability is None:
            return "-"
        return f"{self.ai_off_topic_probability * 100:.0f}%"


class ProcessingLog(models.Model):
    """Processing audit log for an inbound request."""

    inbound_request = models.ForeignKey(InboundRequest, on_delete=models.CASCADE, related_name="processing_logs")
    step = models.CharField(max_length=80, db_index=True)
    status = models.CharField(max_length=32, db_index=True)
    message = models.TextField(blank=True)
    details_json = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]


class BlocklistKind(models.TextChoices):
    """Supported blocklist value kinds."""

    PHONE = "phone", "Phone"
    IP = "ip", "IP"
    EMAIL_DOMAIN = "email_domain", "Email domain"


class Blocklist(models.Model):
    """Values blocked by a head user."""

    value = models.CharField(max_length=255, db_index=True)
    kind = models.CharField(max_length=32, choices=BlocklistKind.choices, db_index=True)
    reason = models.TextField(blank=True)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="blocklist_entries")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("value", "kind")]
        ordering = ["kind", "value"]


class IntakeThrottleScope(models.TextChoices):
    """Throttle buckets."""

    IP = "ip", "IP"
    GLOBAL = "global", "Global"


class IntakeThrottle(models.Model):
    """Simple fixed-window rate limit counter."""

    scope = models.CharField(max_length=16, choices=IntakeThrottleScope.choices)
    key = models.CharField(max_length=255)
    window_start = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("scope", "key", "window_start")]
        indexes = [models.Index(fields=["scope", "key", "window_start"])]


class IdempotencyKey(models.Model):
    """Maps a source event key to the first stored request."""

    key = models.CharField(max_length=255, unique=True)
    first_request = models.ForeignKey(InboundRequest, on_delete=models.CASCADE, related_name="idempotency_keys")
    created_at = models.DateTimeField(default=timezone.now)


class WebhookSettings(models.Model):
    """Singleton — head-controlled HMAC secret for the intake webhook."""

    webhook_secret = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_webhook_settings",
    )
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Webhook settings"

    def __str__(self) -> str:
        return "Webhook intake settings"

    @property
    def has_secret(self) -> bool:
        return bool(self.webhook_secret)

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        super().save(*args, **kwargs)

    @classmethod
    def current(cls) -> "WebhookSettings":
        """Return singleton, seeding from env if the row doesn't exist yet."""
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={"webhook_secret": settings.WEBHOOK_SECRET or ""},
        )
        return obj
