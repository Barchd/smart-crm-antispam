"""Helpers for Telegram bot settings and connection checks."""

from __future__ import annotations

from dataclasses import dataclass

import re

import httpx
from django.conf import settings
from django.db import OperationalError, ProgrammingError

from .models import BotSettings


@dataclass(frozen=True)
class BotConfig:
    """Runtime Telegram bot configuration."""

    bot_token: str
    admin_chat_id: str
    admin_telegram_ids: set[int]
    customer_prompt: str = ""


@dataclass(frozen=True)
class BotConnectionCheckResult:
    """User-facing Telegram API check result."""

    ok: bool
    message: str


def mask_secret(value: str) -> str:
    """Return a non-sensitive token mask for UI display."""

    if not value:
        return ""
    tail = value[-4:] if len(value) >= 4 else "****"
    return f"***{tail}"


def get_bot_config() -> BotConfig:
    """Read DB bot settings with env fallback before migrations are available."""

    try:
        current = BotSettings.current()
    except (OperationalError, ProgrammingError):
        return BotConfig(
            bot_token=settings.BOT_TOKEN or "",
            admin_chat_id=settings.ADMIN_CHAT_ID or "",
            admin_telegram_ids=set(settings.ADMIN_TELEGRAM_IDS),
            customer_prompt="",
        )

    return BotConfig(
        bot_token=current.bot_token,
        admin_chat_id=current.admin_chat_id,
        admin_telegram_ids=current.allowed_user_ids(),
        customer_prompt=current.customer_prompt.strip()[:4000],
    )


def customer_prompt_for_source(source_type: str) -> str:
    """Return trusted head-configured guidance only for Telegram customer messages."""

    if (source_type or "").strip().lower() != "telegram":
        return ""
    return get_bot_config().customer_prompt


def check_bot_connection(config: BotConfig | None = None, *, timeout: float = 10.0) -> BotConnectionCheckResult:
    """Check Telegram getMe without exposing the token."""

    cfg = config or get_bot_config()
    if not cfg.bot_token:
        return BotConnectionCheckResult(ok=False, message="Telegram bot token не задан")
    try:
        response = httpx.get(f"https://api.telegram.org/bot{cfg.bot_token}/getMe", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        sanitized = re.sub(re.escape(cfg.bot_token), "***", str(exc))
        return BotConnectionCheckResult(ok=False, message=f"Telegram API недоступен: {sanitized}")

    if isinstance(payload, dict) and payload.get("ok") is True:
        username = payload.get("result", {}).get("username", "")
        suffix = f" @{username}" if username else ""
        return BotConnectionCheckResult(ok=True, message=f"Telegram bot доступен{suffix}")
    return BotConnectionCheckResult(ok=False, message="Telegram API вернул ошибку для bot token")
