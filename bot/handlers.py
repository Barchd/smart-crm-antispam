"""aiogram handlers for allowlisted admin commands."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .services import open_request_link, render_errors, render_recent, render_stats, retry_request


admin_router = Router()


def parse_request_id(text: str) -> int | None:
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


@admin_router.message(Command("recent"))
async def recent_handler(message: Message):
    await message.answer(render_recent(), parse_mode=None)


@admin_router.message(Command("errors"))
async def errors_handler(message: Message):
    await message.answer(render_errors(), parse_mode=None)


@admin_router.message(Command("stats"))
async def stats_handler(message: Message):
    await message.answer(render_stats(), parse_mode=None)


@admin_router.message(Command("open"))
async def open_handler(message: Message):
    request_id = parse_request_id(message.text or "")
    if request_id is None:
        await message.answer("Заявка не найдена.", parse_mode=None)
        return
    link = open_request_link(request_id=request_id)
    await message.answer(link or "Заявка не найдена.", parse_mode=None)


@admin_router.message(Command("retry"))
async def retry_handler(message: Message):
    request_id = parse_request_id(message.text or "")
    if request_id is None:
        await message.answer("Заявка не найдена.", parse_mode=None)
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data=f"retry_confirm:{request_id}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"retry_cancel:{request_id}"),
            ]
        ]
    )
    await message.answer(f"Повторно обработать заявку #{request_id}?", reply_markup=keyboard, parse_mode=None)


@admin_router.callback_query(F.data.startswith("retry_confirm:"))
async def retry_confirm_handler(callback: CallbackQuery):
    request_id = int(callback.data.split(":", 1)[1])
    user_id = callback.from_user.id if callback.from_user else 0
    inbound = retry_request(request_id=request_id, telegram_user_id=user_id)
    await callback.answer("Готово" if inbound else "Заявка не найдена")
    if callback.message:
        await callback.message.answer("Заявка поставлена в обработку." if inbound else "Заявка не найдена.", parse_mode=None)


@admin_router.callback_query(F.data.startswith("retry_cancel:"))
async def retry_cancel_handler(callback: CallbackQuery):
    await callback.answer("Отменено")
