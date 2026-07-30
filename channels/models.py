"""Channel-agnostic customer messaging models."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class ChannelType(models.TextChoices):
    """Supported external customer message transports."""

    SITE = "site", "Сайт"
    TELEGRAM = "telegram", "Telegram"
    WHATSAPP = "whatsapp", "WhatsApp"
    EMAIL = "email", "Email"
    OTHER = "other", "Другой канал"


class MessageDirection(models.TextChoices):
    """Direction of a customer message."""

    INBOUND = "inbound", "Входящее"
    OUTBOUND = "outbound", "Исходящее"


class MessageStatus(models.TextChoices):
    """Delivery lifecycle for stored messages."""

    RECEIVED = "received", "Получено"
    PENDING = "pending", "Ожидает отправки"
    SENT = "sent", "Отправлено"
    FAILED = "failed", "Ошибка отправки"


class DeliveryStatus(models.TextChoices):
    """Result of one outbound delivery attempt."""

    SUCCESS = "success", "Успешно"
    FAILED = "failed", "Ошибка"


class Channel(models.Model):
    """External channel definition, independent from CRM business logic."""

    type = models.CharField(max_length=32, choices=ChannelType.choices, db_index=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    settings_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["type", "name", "id"]
        unique_together = [("type", "name")]

    def __str__(self) -> str:
        return f"{self.get_type_display()} · {self.name}"


class DialogQuerySet(models.QuerySet):
    """Visibility rules for customer dialogs."""

    def visible_to(self, user):
        if not getattr(user, "is_authenticated", False):
            return self.none()
        if getattr(user, "is_head", False):
            return self.all()
        if getattr(user, "is_manager", False):
            return self.filter(deal__manager=user)
        return self.none()


class Dialog(models.Model):
    """Conversation thread bound to a channel, client and deal."""

    objects = DialogQuerySet.as_manager()

    channel = models.ForeignKey(Channel, on_delete=models.PROTECT, related_name="dialogs")
    client = models.ForeignKey("crm.Client", on_delete=models.PROTECT, related_name="dialogs")
    deal = models.ForeignKey("crm.Deal", on_delete=models.CASCADE, related_name="dialogs")
    external_thread_id = models.CharField(max_length=255)
    last_inbound_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_message_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_message_at", "-id"]
        unique_together = [("channel", "external_thread_id")]
        indexes = [
            models.Index(fields=["deal", "last_message_at"]),
            models.Index(fields=["channel", "external_thread_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.channel} · {self.external_thread_id}"


class Message(models.Model):
    """One inbound or outbound message in a customer dialog."""

    dialog = models.ForeignKey(Dialog, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(max_length=16, choices=MessageDirection.choices, db_index=True)
    status = models.CharField(max_length=24, choices=MessageStatus.choices, default=MessageStatus.RECEIVED, db_index=True)
    text = models.TextField()
    payload_json = models.JSONField(default=dict, blank=True)
    external_message_id = models.CharField(max_length=255, blank=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="sent_channel_messages")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["dialog", "created_at"]),
            models.Index(fields=["direction", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.direction} #{self.id}"


class DeliveryLog(models.Model):
    """Audit log for outbound delivery attempts."""

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="delivery_logs")
    status = models.CharField(max_length=16, choices=DeliveryStatus.choices, db_index=True)
    adapter = models.CharField(max_length=64)
    response_json = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.adapter} {self.status} for message {self.message_id}"
