"""Run the administrative Telegram bot with long polling."""

from __future__ import annotations

import asyncio

from django.core.management.base import BaseCommand

from bot.app import create_bot, create_dispatcher


class Command(BaseCommand):
    help = "Run admin Telegram bot."

    def handle(self, *args, **options):
        bot = create_bot()
        dispatcher = create_dispatcher()
        asyncio.run(dispatcher.start_polling(bot))

