"""Authentication helpers for CRM login flow."""

from __future__ import annotations


def get_client_ip(request) -> str | None:
    """Return best-effort client IP for audit and throttling."""

    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR")


