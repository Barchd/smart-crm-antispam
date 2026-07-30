"""Outbound delivery adapters for customer messaging."""

from __future__ import annotations

from dataclasses import dataclass
import re

import httpx

from bot.config import check_bot_connection, get_bot_config

from .models import ChannelType, Dialog


@dataclass(frozen=True)
class DeliveryResult:
    """Normalized result of an outbound send attempt."""

    ok: bool
    adapter: str
    response_json: dict
    error: str = ""
    external_message_id: str = ""


class BaseChannelAdapter:
    """Base adapter contract for all customer message transports."""

    adapter_name = "base"

    def send(self, *, dialog: Dialog, text: str) -> DeliveryResult:
        raise NotImplementedError


class SiteChannelAdapter(BaseChannelAdapter):
    """MVP adapter for website/mock chat: message is stored as delivered in CRM."""

    adapter_name = "site"

    def send(self, *, dialog: Dialog, text: str) -> DeliveryResult:
        return DeliveryResult(
            ok=True,
            adapter=self.adapter_name,
            response_json={"stored": True, "channel": dialog.channel.type, "external_thread_id": dialog.external_thread_id},
            external_message_id=f"local-{dialog.id}",
        )


class TelegramChannelAdapter(BaseChannelAdapter):
    """Telegram customer transport using DB-backed bot settings."""

    adapter_name = "telegram"

    def send(self, *, dialog: Dialog, text: str) -> DeliveryResult:
        from intake.services import telegram_customer_is_blocked

        if dialog.deal.is_spam or telegram_customer_is_blocked(dialog.external_thread_id):
            return DeliveryResult(
                ok=False,
                adapter=self.adapter_name,
                response_json={},
                error="Telegram thread заблокирован модерацией",
            )
        config = get_bot_config()
        if not config.bot_token:
            return DeliveryResult(ok=False, adapter=self.adapter_name, response_json={}, error="Telegram bot token не задан")

        connection = check_bot_connection(config)
        if not connection.ok:
            return DeliveryResult(
                ok=False,
                adapter=self.adapter_name,
                response_json={},
                error=f"Telegram bot недоступен: {connection.message}",
            )

        try:
            response = httpx.post(
                f"https://api.telegram.org/bot{config.bot_token}/sendMessage",
                json={"chat_id": dialog.external_thread_id, "text": text},
                timeout=10.0,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return DeliveryResult(ok=False, adapter=self.adapter_name, response_json={}, error=_sanitize_error(str(exc), config.bot_token))

        if payload.get("ok") is True:
            message_id = str(payload.get("result", {}).get("message_id") or "")
            return DeliveryResult(ok=True, adapter=self.adapter_name, response_json=payload, external_message_id=message_id)
        error = str(payload.get("description") or "Telegram API вернул ошибку")
        return DeliveryResult(ok=False, adapter=self.adapter_name, response_json=payload, error=_sanitize_error(error, config.bot_token))


def _sanitize_error(value: str, token: str) -> str:
    """Remove Telegram token from errors before writing DeliveryLog."""

    if not token:
        return value
    return re.sub(re.escape(token), "***", value)


def adapter_for_dialog(dialog: Dialog) -> BaseChannelAdapter:
    """Return an outbound adapter for the dialog channel."""

    if dialog.channel.type == ChannelType.TELEGRAM:
        return TelegramChannelAdapter()
    return SiteChannelAdapter()
