"""Logical fingerprint clustering for inbound requests (no physical row merge)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone

from intake.models import InboundRequest, InboundRequestStatus
from intake.risk import UA_MIN_LENGTH

CLUSTER_WINDOW_DAYS = 7


def _normalize_ua(ua: str) -> str:
    return ua.strip().casefold()


def cluster_key(inbound: InboundRequest) -> str | None:
    """Stable label for UI: IP and/or UA when present (Telegram skipped)."""

    if (inbound.source_type or "").casefold() == "telegram":
        return None
    parts: list[str] = []
    if inbound.ip_address:
        parts.append(f"ip:{inbound.ip_address}")
    ua = _normalize_ua(inbound.user_agent or "")
    if len(ua) >= UA_MIN_LENGTH:
        parts.append(f"ua:{ua[:48]}")
    return "+".join(parts) if parts else None


def related_requests(inbound: InboundRequest, *, include_self: bool = False) -> QuerySet:
    """Peers sharing the same User-Agent and/or the same IP (OR)."""

    if (inbound.source_type or "").casefold() == "telegram":
        return InboundRequest.objects.none()

    filters = Q()
    ua_raw = (inbound.user_agent or "").strip()
    if len(_normalize_ua(ua_raw)) >= UA_MIN_LENGTH:
        filters |= Q(user_agent__iexact=ua_raw)
    if inbound.ip_address:
        filters |= Q(ip_address=inbound.ip_address)
    if not filters:
        return InboundRequest.objects.none()

    qs = InboundRequest.objects.filter(filters).exclude(source_type__iexact="telegram")

    # No time cap for blocked/suspicious; 7-day rolling window otherwise.
    if inbound.status not in (InboundRequestStatus.BLOCKED, InboundRequestStatus.SUSPICIOUS):
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=CLUSTER_WINDOW_DAYS))

    if not include_self:
        qs = qs.exclude(pk=inbound.pk)

    return qs.order_by("created_at")


@dataclass(frozen=True)
class ClusterInfo:
    key: str
    count: int
    unique_phones: list[str]
    unique_emails: list[str]
    max_risk: int
    message_texts: list[str]
    request_ids: list[int]


def cluster_info(inbound: InboundRequest) -> ClusterInfo | None:
    """Aggregate cluster data for the Admin Ops card. Returns None if no related requests."""

    key = cluster_key(inbound)
    if key is None:
        return None

    qs = related_requests(inbound, include_self=False)
    count = qs.count()
    if count == 0:
        return None

    unique_phones = list(
        qs.exclude(phone_normalized="").values_list("phone_normalized", flat=True).distinct()
    )
    # Fallback: raw phones when normalized not filled yet.
    if not unique_phones:
        unique_phones = list(qs.exclude(phone_raw="").values_list("phone_raw", flat=True).distinct())

    unique_emails = list(qs.exclude(email_raw="").values_list("email_raw", flat=True).distinct())
    texts_with_ts = list(
        qs.exclude(message_text="").order_by("created_at").values_list("message_text", flat=True)
    )
    request_ids = list(qs.values_list("pk", flat=True))
    risks = list(qs.values_list("risk_score_final", flat=True))
    max_risk_val = max((r or 0) for r in risks) if risks else 0

    return ClusterInfo(
        key=key,
        count=count,
        unique_phones=unique_phones,
        unique_emails=unique_emails,
        max_risk=max_risk_val,
        message_texts=texts_with_ts,
        request_ids=request_ids,
    )
