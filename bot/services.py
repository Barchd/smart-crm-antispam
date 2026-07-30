"""ORM services used by the admin Telegram bot."""

from __future__ import annotations

from types import SimpleNamespace

from django.db.models import Count

from intake.models import InboundRequest, InboundRequestStatus
from intake.services import retry_inbound_request

from .formatters import format_errors, format_open_link, format_recent, format_stats


def recent_requests(limit: int = 5):
    return InboundRequest.objects.select_related("linked_deal").order_by("-created_at", "-id")[:limit]


def error_requests(limit: int = 5):
    return InboundRequest.objects.filter(status__in=[InboundRequestStatus.RETRY_WAIT, InboundRequestStatus.FAILED]).order_by("-updated_at", "-id")[:limit]


def render_recent(limit: int = 5) -> str:
    return format_recent(recent_requests(limit=limit))


def render_errors(limit: int = 5) -> str:
    return format_errors(error_requests(limit=limit))


def retry_request(*, request_id: int, telegram_user_id: int) -> InboundRequest | None:
    """Retry a failed/retry_wait request — thin wrapper over the shared CRM service.

    Enforces the same status guard and field resets as the CRM retry action.
    Returns None if the request doesn't exist or has a forbidden status.
    """
    inbound = InboundRequest.objects.filter(id=request_id).first()
    if inbound is None:
        return None
    try:
        return retry_inbound_request(inbound=inbound, user=SimpleNamespace(id=telegram_user_id))
    except ValueError:
        return None


def open_request_link(*, request_id: int) -> str | None:
    inbound = InboundRequest.objects.filter(id=request_id).first()
    if inbound is None:
        return None
    return format_open_link(inbound)


def render_stats() -> str:
    counts = dict(InboundRequest.objects.values("status").annotate(count=Count("id")).values_list("status", "count"))
    return format_stats(
        total=sum(counts.values()),
        retry_wait=counts.get(InboundRequestStatus.RETRY_WAIT, 0),
        failed=counts.get(InboundRequestStatus.FAILED, 0),
        suspicious=counts.get(InboundRequestStatus.SUSPICIOUS, 0),
    )


def open_request_link(*, request_id: int) -> str | None:
    inbound = InboundRequest.objects.filter(id=request_id).first()
    if inbound is None:
        return None
    return format_open_link(inbound)


def render_stats() -> str:
    counts = dict(InboundRequest.objects.values("status").annotate(count=Count("id")).values_list("status", "count"))
    return format_stats(
        total=sum(counts.values()),
        retry_wait=counts.get(InboundRequestStatus.RETRY_WAIT, 0),
        failed=counts.get(InboundRequestStatus.FAILED, 0),
        suspicious=counts.get(InboundRequestStatus.SUSPICIOUS, 0),
    )

