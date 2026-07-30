"""Factory functions for the aiogram Telegram bot."""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from .config import get_bot_config
from .customer import customer_router
from .handlers import admin_router
from .security import AdminAccessMiddleware


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    admin_router.message.middleware(AdminAccessMiddleware())
    admin_router.callback_query.middleware(AdminAccessMiddleware())
    dispatcher.include_router(admin_router)
    dispatcher.include_router(customer_router)
    return dispatcher


def create_bot() -> Bot:
    config = get_bot_config()
    if not config.bot_token:
        raise RuntimeError("BOT_TOKEN is required to run the Telegram bot")
    return Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=None))
