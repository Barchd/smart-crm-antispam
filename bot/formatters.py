"""Safe Telegram formatters that avoid personal data leakage."""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from intake.models import InboundRequest


def mask_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 4:
        return "***"
    return f"***{digits[-4:]}"


def mask_email(value: str) -> str:
    if "@" not in value:
        return "***"
    name, domain = value.split("@", 1)
    return f"{name[:1]}***@{domain}"


def safe_error_label(value: str) -> str:
    if not value:
        return "нет деталей"
    first = value.strip().splitlines()[0].split(":", 1)[0]
    return first[:80] or "ошибка обработки"


def request_time(inbound: InboundRequest) -> str:
    return timezone.localtime(inbound.created_at).strftime("%H:%M")


def request_meta(inbound: InboundRequest) -> str:
    category = inbound.ai_category or f"risk {inbound.risk_score_final}"
    urgency = f"/{inbound.ai_urgency}" if inbound.ai_urgency else ""
    deal = f" · deal #{inbound.linked_deal_id}" if inbound.linked_deal_id else ""
    retry = f" · попытка {inbound.retry_count}" if inbound.retry_count else ""
    return f"#{inbound.id} · {inbound.source_type} · {request_time(inbound)} · {inbound.status} · {category}{urgency}{retry}{deal}"


def format_recent(requests) -> str:
    lines = [request_meta(inbound) for inbound in requests]
    return "\n".join(lines) if lines else "Заявок пока нет."


def format_errors(requests) -> str:
    lines = [f"{request_meta(inbound)} · {safe_error_label(inbound.last_error)}" for inbound in requests]
    return "\n".join(lines) if lines else "Ошибок нет."


def format_open_link(inbound: InboundRequest) -> str:
    if not inbound.linked_deal_id:
        return "Сделка еще не создана."
    return f"{settings.CRM_BASE_URL.rstrip('/')}/deals/{inbound.linked_deal_id}/"


def format_stats(*, total: int, retry_wait: int, failed: int, suspicious: int) -> str:
    return f"Всего заявок: {total}\nretry_wait: {retry_wait}\nfailed: {failed}\nsuspicious: {suspicious}"

