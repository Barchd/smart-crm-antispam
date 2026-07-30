"""Business services for customer messaging inbox."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from crm.models import Deal, DealLogAction
from crm.services import log_deal_action
from intake.models import InboundRequest

from .adapters import adapter_for_dialog
from .models import Channel, ChannelType, DeliveryLog, DeliveryStatus, Dialog, Message, MessageDirection, MessageStatus


CHANNEL_ALIASES = {
    "site": ChannelType.SITE,
    "web": ChannelType.SITE,
    "website": ChannelType.SITE,
    "telegram": ChannelType.TELEGRAM,
    "tg": ChannelType.TELEGRAM,
    "whatsapp": ChannelType.WHATSAPP,
    "wa": ChannelType.WHATSAPP,
    "email": ChannelType.EMAIL,
    "mail": ChannelType.EMAIL,
}


def normalize_channel_type(value: str) -> str:
    """Map arbitrary source strings to supported channel types."""

    return CHANNEL_ALIASES.get((value or "").strip().lower(), ChannelType.OTHER)


def get_or_create_channel(*, source_type: str, source_name: str = "") -> Channel:
    """Return a stable channel record for incoming source metadata."""

    channel_type = normalize_channel_type(source_type)
    channel_name = (source_name or source_type or channel_type).strip() or ChannelType.OTHER
    channel, _ = Channel.objects.get_or_create(type=channel_type, name=channel_name)
    return channel


def external_thread_id_from_payload(*, inbound: InboundRequest) -> str:
    """Pick a channel thread id without trusting AI output."""

    payload: dict[str, Any] = inbound.raw_payload_json or {}
    if normalize_channel_type(inbound.source_type) == ChannelType.TELEGRAM:
        for key in ("user_id", "chat_id", "thread_id", "dialog_id", "conversation_id"):
            value = payload.get(key)
            if value:
                return str(value)
    for key in ("chat_id", "thread_id", "dialog_id", "conversation_id", "user_id", "email"):
        value = payload.get(key)
        if value:
            return str(value)
    if inbound.email_raw:
        return inbound.email_raw
    if inbound.phone_normalized:
        return inbound.phone_normalized
    return f"{inbound.source_type}:{inbound.external_id}"


def dialog_for_inbound_request(*, inbound: InboundRequest) -> Dialog | None:
    """Return an existing dialog for the inbound channel thread."""

    thread_id = external_thread_id_from_payload(inbound=inbound)
    channel_type = normalize_channel_type(inbound.source_type)
    return (
        Dialog.objects.select_related("client", "deal", "channel")
        .filter(channel__type=channel_type, external_thread_id=thread_id)
        .order_by("-last_message_at", "-id")
        .first()
    )


def conversation_context_for_inbound(*, inbound: InboundRequest, limit: int | None = 20, since=None) -> str:
    """Build dialog context, optionally starting at a moderation checkpoint."""

    def is_after_checkpoint(value) -> bool:
        if since is None:
            return True
        if value is None:
            return True
        parsed = value if hasattr(value, "tzinfo") else parse_datetime(str(value))
        if parsed is None:
            return True
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone=timezone.get_current_timezone())
        return parsed > since

    dialog = dialog_for_inbound_request(inbound=inbound)
    lines: list[str] = []
    stored_external_ids: set[str] = set()
    if dialog is not None:
        messages_qs = dialog.messages.order_by("-created_at", "-id")
        messages = messages_qs[:limit] if limit is not None else messages_qs
        for message in reversed(list(messages)):
            if not is_after_checkpoint(message.created_at):
                continue
            role = "клиент" if message.direction == MessageDirection.INBOUND else "менеджер"
            text = " ".join((message.text or "").split())
            if text:
                lines.append(f"{role}: {text}")
            if message.direction == MessageDirection.INBOUND and message.external_message_id:
                stored_external_ids.add(str(message.external_message_id))

    if normalize_channel_type(inbound.source_type) == ChannelType.TELEGRAM:
        payload = inbound.raw_payload_json or {}
        telegram_payloads = [payload]
        telegram_payloads.extend(item for item in payload.get("follow_up_messages", []) if isinstance(item, dict))
        for telegram_payload in telegram_payloads:
            if not is_after_checkpoint(telegram_payload.get("received_at")):
                continue
            external_message_id = str(telegram_payload.get("message_id") or "")
            if external_message_id and external_message_id in stored_external_ids:
                continue
            text = " ".join(str(telegram_payload.get("text") or "").split())
            line = f"клиент: {text}"
            if text and (external_message_id or line not in lines):
                lines.append(line)
            if external_message_id:
                stored_external_ids.add(external_message_id)

    current_text = " ".join((inbound.message_text or "").split())
    current_is_after_checkpoint = is_after_checkpoint(inbound.received_at)
    if current_text and current_is_after_checkpoint and (not lines or lines[-1] != f"клиент: {current_text}"):
        lines.append(f"клиент: {current_text}")
    return "\n".join(lines)


@transaction.atomic
def bind_inbound_request_to_dialog(*, inbound: InboundRequest, deal: Deal) -> Dialog:
    """Create or update the dialog and store the inbound message."""

    channel = get_or_create_channel(source_type=inbound.source_type, source_name=inbound.source_name)
    thread_id = external_thread_id_from_payload(inbound=inbound)
    now = timezone.now()
    dialog = Dialog.objects.filter(channel__type=channel.type, external_thread_id=thread_id).order_by("-last_message_at", "-id").first()
    if dialog is None:
        dialog = Dialog.objects.create(
            channel=channel,
            external_thread_id=thread_id,
            client=deal.client,
            deal=deal,
            last_inbound_at=inbound.received_at,
            last_message_at=inbound.received_at,
        )
    updates: list[str] = []
    if dialog.channel_id != channel.id:
        dialog.channel = channel
        updates.append("channel")
    if dialog.client_id != deal.client_id:
        dialog.client = deal.client
        updates.append("client")
    if dialog.deal_id != deal.id:
        dialog.deal = deal
        updates.append("deal")
    dialog.last_inbound_at = inbound.received_at or now
    dialog.last_message_at = inbound.received_at or now
    updates.extend(["last_inbound_at", "last_message_at", "updated_at"])
    dialog.save(update_fields=updates)

    stored = InboundRequest.objects.only("raw_payload_json", "message_text", "received_at").get(pk=inbound.pk)
    primary_payload = stored.raw_payload_json or {}
    payloads = [primary_payload]
    payloads.extend(item for item in primary_payload.get("follow_up_messages", []) if isinstance(item, dict))
    for index, payload in enumerate(payloads):
        external_message_id = str(payload.get("message_id") or (inbound.external_id if index == 0 else ""))
        text = str(payload.get("text") or (stored.message_text if index == 0 else "")).strip()
        if not text:
            continue
        if external_message_id and Message.objects.filter(
            dialog=dialog,
            direction=MessageDirection.INBOUND,
            external_message_id=external_message_id,
        ).exists():
            continue
        Message.objects.create(
            dialog=dialog,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            text=text,
            payload_json=payload,
            external_message_id=external_message_id,
            created_at=stored.received_at if index == 0 else now,
        )
    return dialog


@transaction.atomic
def append_inbound_dialog_message(*, dialog: Dialog, text: str, payload: dict) -> Message:
    """Append one transport message to an existing dialog without creating an intake request."""

    external_message_id = str(payload.get("message_id") or "")
    existing = None
    if external_message_id:
        existing = Message.objects.filter(
            dialog=dialog,
            direction=MessageDirection.INBOUND,
            external_message_id=external_message_id,
        ).first()
    if existing is not None:
        return existing

    now = timezone.now()
    message = Message.objects.create(
        dialog=dialog,
        direction=MessageDirection.INBOUND,
        status=MessageStatus.RECEIVED,
        text=text.strip(),
        payload_json=payload,
        external_message_id=external_message_id,
        created_at=now,
    )
    dialog.last_inbound_at = now
    dialog.last_message_at = now
    dialog.save(update_fields=["last_inbound_at", "last_message_at", "updated_at"])
    Deal.objects.filter(pk=dialog.deal_id).update(updated_at=now)
    return message


@transaction.atomic
def send_dialog_message(*, dialog: Dialog, deal: Deal, text: str, user) -> Message:
    """Create an outbound message and deliver it through the dialog channel adapter."""

    clean_text = text.strip()
    if not clean_text:
        raise ValueError("Текст ответа не может быть пустым")
    if dialog.deal_id != deal.id:
        raise ValueError("Диалог не относится к этой сделке")

    message = Message.objects.create(
        dialog=dialog,
        direction=MessageDirection.OUTBOUND,
        status=MessageStatus.PENDING,
        text=clean_text,
        sent_by=user,
    )
    result = adapter_for_dialog(dialog).send(dialog=dialog, text=clean_text)
    if result.ok:
        message.status = MessageStatus.SENT
        message.sent_at = timezone.now()
        message.external_message_id = result.external_message_id
        delivery_status = DeliveryStatus.SUCCESS
        error = ""
    else:
        message.status = MessageStatus.FAILED
        delivery_status = DeliveryStatus.FAILED
        error = result.error
    message.save(update_fields=["status", "sent_at", "external_message_id"])
    DeliveryLog.objects.create(
        message=message,
        status=delivery_status,
        adapter=result.adapter,
        response_json=result.response_json,
        error=error,
    )

    deal.reply_draft = clean_text
    deal.reply_approved_at = timezone.now()
    deal.reply_approved_by = user
    deal.save(update_fields=["reply_draft", "reply_approved_at", "reply_approved_by", "updated_at"])
    dialog.last_message_at = message.sent_at or message.created_at
    dialog.save(update_fields=["last_message_at", "updated_at"])
    log_deal_action(deal=deal, action=DealLogAction.REPLY_APPROVED, user=user)
    return message
