"""Access control and rate limiting for the admin Telegram bot."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import timedelta
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message
from django.utils import timezone

from .config import get_bot_config


logger = logging.getLogger(__name__)


def allowed_user_ids() -> set[int]:
    """Return Telegram user ids allowed to use the chat-bot."""

    config = get_bot_config()
    ids = set(config.admin_telegram_ids)
    if config.admin_chat_id:
        try:
            ids.add(int(config.admin_chat_id))
        except (TypeError, ValueError):
            logger.warning("ADMIN_CHAT_ID is not an integer")
    return ids


def event_user_id(event: Message | CallbackQuery) -> int | None:
    return event.from_user.id if event.from_user else None


def event_chat_type(event: Message | CallbackQuery) -> str | None:
    if isinstance(event, CallbackQuery):
        return event.message.chat.type if event.message else None
    return event.chat.type


def is_authorized_event(event: Message | CallbackQuery) -> bool:
    """Check private chat and from_user allowlist."""

    user_id = event_user_id(event)
    return bool(user_id and event_chat_type(event) == "private" and user_id in allowed_user_ids())


class CommandRateLimiter:
    """Simple in-memory command limiter for the MVP bot process."""

    def __init__(self, *, limit: int = 5, window_seconds: int = 60):
        self.limit = limit
        self.window = timedelta(seconds=window_seconds)
        self._events: dict[int, deque] = defaultdict(deque)

    def allow(self, user_id: int, now=None) -> bool:
        now = now or timezone.now()
        bucket = self._events[user_id]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        return True


class AdminAccessMiddleware(BaseMiddleware):
    """Outer middleware that protects all bot handlers in one place."""

    def __init__(self, *, limiter: CommandRateLimiter | None = None):
        self.limiter = limiter or CommandRateLimiter()

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        user_id = event_user_id(event)
        if not is_authorized_event(event):
            logger.warning("unauthorized access attempt from tg_user=%s", user_id)
            return None
        if user_id is not None and not self.limiter.allow(user_id):
            if isinstance(event, CallbackQuery):
                await event.answer("Слишком много команд, попробуйте позже.")
            else:
                await event.answer("Слишком много команд, попробуйте позже.")
            return None
        return await handler(event, data)
