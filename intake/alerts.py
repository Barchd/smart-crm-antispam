"""Alert hook used by worker now and Telegram bot in later phases."""

from __future__ import annotations

from .models import InboundRequest, ProcessingLog


def notify_critical_processing_event(*, inbound: InboundRequest, event: str, message: str = "") -> None:
    """Record an alert-worthy event until the real bot is implemented."""

    ProcessingLog.objects.create(
        inbound_request=inbound,
        step="bot_alert_pending",
        status=inbound.status,
        message=message[:200],
        details_json={"event": event},
    )

