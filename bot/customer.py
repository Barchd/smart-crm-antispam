"""Customer-facing Telegram intake flow."""

from __future__ import annotations

from dataclasses import dataclass

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from ai.speech import transcribe_telegram_voice
from channels.models import ChannelType, Dialog
from channels.services import append_inbound_dialog_message, bind_inbound_request_to_dialog
from intake.models import InboundRequest, InboundRequestStatus, ProcessingLog
from intake.services import create_raw_inbound_request, payload_hash, telegram_customer_is_blocked


customer_router = Router()

CUSTOMER_WAITING_MANAGER_MESSAGE = "Спасибо! Вопрос передан менеджеру. Менеджер ответит здесь."


class LeadFlow(StatesGroup):
    """FSM states for a customer lead request."""

    waiting_name = State()
    waiting_phone = State()
    waiting_question = State()


@dataclass(frozen=True)
class TelegramLead:
    """Normalized customer lead data collected in Telegram."""

    external_id: str
    name: str
    phone: str
    text: str
    payload: dict


def phone_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard that requests the user's Telegram contact."""

    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отправить телефон", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Нажмите кнопку, чтобы отправить телефон",
    )


def build_lead_from_message(message: Message, *, name: str, phone: str, question: str) -> TelegramLead:
    """Build a raw intake payload from Telegram user data."""

    from_user = message.from_user
    chat = message.chat
    thread_id = telegram_user_thread_id(message)
    external_id = f"tg-lead:{thread_id}:{message.message_id}"
    text = question.strip()
    payload = {
        "external_id": external_id,
        "source": "telegram",
        "source_name": "Telegram",
        "chat_id": chat.id,
        "user_id": str(from_user.id) if from_user else "",
        "username": from_user.username if from_user else "",
        "language_code": getattr(from_user, "language_code", "") if from_user else "",
        "message_id": message.message_id,
        "name": name,
        "phone": phone,
        "text": text,
        "received_at": timezone.now().isoformat(),
    }
    return TelegramLead(external_id=external_id, name=name, phone=phone, text=text, payload=payload)


def telegram_user_thread_id(message: Message) -> str:
    """Return the stable Telegram customer identifier used by channel dialogs."""

    if message.from_user:
        return str(message.from_user.id)
    return str(message.chat.id)


def normalize_telegram_payload(payload: dict) -> dict:
    """Keep Telegram's stable user id in one JSON type across the whole thread."""

    normalized = dict(payload)
    user_id = normalized.get("user_id")
    if user_id not in (None, ""):
        normalized["user_id"] = str(user_id)
    return normalized


def create_telegram_inbound_request(lead: TelegramLead) -> InboundRequest:
    """Persist a Telegram customer lead for the normal intake worker.

    Uses the shared create_raw_inbound_request helper to guarantee the same
    field invariants and audit log as HTTP intake (no HMAC/throttle — those
    are HTTP-only concerns for Telegram transport).
    """
    normalized_payload = normalize_telegram_payload(lead.payload)
    return create_raw_inbound_request(
        external_id=lead.external_id,
        source_type="telegram",
        source_name="Telegram",
        name_raw=lead.name,
        phone_raw=lead.phone,
        message_text=lead.text,
        received_at=timezone.now(),
        raw_payload_json=normalized_payload,
        headers_json={},
        user_agent="telegram-bot",
        log_message="Telegram customer lead",
        trust_level="internal",
    )


def _telegram_inbound_for_user(user_id: int | str) -> InboundRequest | None:
    """Return the canonical intake row for a Telegram customer thread."""

    candidates: list[int | str] = [str(user_id)]
    try:
        candidates.insert(0, int(user_id))
    except (TypeError, ValueError):
        pass
    for candidate in candidates:
        inbound = (
            InboundRequest.objects.filter(source_type="telegram", raw_payload_json__user_id=candidate)
            .order_by("created_at", "id")
            .first()
        )
        if inbound is not None:
            return inbound
    return None


@transaction.atomic
def route_telegram_customer_message(lead: TelegramLead) -> InboundRequest | None:
    """Create the first intake row, then reuse it for all messages in the Telegram thread."""

    normalized_payload = normalize_telegram_payload(lead.payload)
    user_id = normalized_payload.get("user_id") or normalized_payload.get("chat_id")
    if telegram_customer_is_blocked(user_id):
        return None
    thread_id = str(user_id)
    dialog = (
        Dialog.objects.select_related("deal", "client", "channel")
        .filter(channel__type=ChannelType.TELEGRAM, external_thread_id=thread_id)
        .order_by("-last_message_at", "-id")
        .first()
    )
    inbound = _telegram_inbound_for_user(user_id)

    if inbound is None and dialog is None:
        return create_telegram_inbound_request(lead)

    if inbound is None:
        append_inbound_dialog_message(dialog=dialog, text=lead.text, payload=normalized_payload)
        return None

    inbound = InboundRequest.objects.select_for_update().get(pk=inbound.pk)
    if dialog is None and inbound.linked_deal_id:
        dialog = bind_inbound_request_to_dialog(inbound=inbound, deal=inbound.linked_deal)

    payload = normalize_telegram_payload(inbound.raw_payload_json or {})
    follow_ups = [item for item in payload.get("follow_up_messages", []) if isinstance(item, dict)]
    message_id = str(normalized_payload.get("message_id") or "")
    known_ids = {str(payload.get("message_id") or "")}
    known_ids.update(str(item.get("message_id") or "") for item in follow_ups)
    if message_id and message_id in known_ids:
        return inbound

    follow_ups.append(normalized_payload)
    payload["follow_up_messages"] = follow_ups
    inbound.raw_payload_json = payload
    inbound.message_text = lead.text
    inbound.name_raw = inbound.name_raw or lead.name
    inbound.phone_raw = inbound.phone_raw or lead.phone
    update_fields = ["raw_payload_json", "message_text", "name_raw", "phone_raw", "updated_at"]

    if inbound.status == InboundRequestStatus.PROCESSING:
        payload["reprocess_after_current"] = True
    elif inbound.status != InboundRequestStatus.BLOCKED:
        inbound.status = InboundRequestStatus.RECEIVED
        inbound.retry_count = 0
        inbound.next_retry_at = None
        inbound.locked_at = None
        inbound.last_error = ""
        inbound.processed_at = None
        update_fields.extend(["status", "retry_count", "next_retry_at", "locked_at", "last_error", "processed_at"])
    inbound.save(update_fields=update_fields)
    ProcessingLog.objects.create(
        inbound_request=inbound,
        step="telegram_followup_queued",
        status=inbound.status,
        message=message_id,
        details_json={"dialog_id": dialog.id if dialog else None},
    )
    return inbound


def existing_customer_data_for_chat(chat_id: int | str) -> dict[str, str] | None:
    """Return known Telegram customer data from a dialog or saved intake request."""

    dialog = (
        Dialog.objects.select_related("client", "deal", "channel")
        .filter(channel__type=ChannelType.TELEGRAM, external_thread_id=str(chat_id))
        .order_by("-last_message_at", "-id")
        .first()
    )
    if dialog is None:
        return None
    return {
        "name": dialog.client.name or "Без имени",
        "phone": dialog.client.phone_raw or dialog.client.phone_normalized,
    }


def existing_customer_data_for_telegram_user(user_id: int | str) -> dict[str, str] | None:
    """Return known customer data by stable Telegram user id."""

    known_dialog = existing_customer_data_for_chat(user_id)
    if known_dialog:
        return known_dialog

    candidates: list[int | str] = [str(user_id)]
    try:
        candidates.insert(0, int(user_id))
    except (TypeError, ValueError):
        pass

    inbound = None
    for candidate in candidates:
        inbound = (
            InboundRequest.objects.filter(source_type="telegram", raw_payload_json__user_id=candidate)
            .exclude(name_raw="")
            .exclude(phone_raw="")
            .order_by("-created_at", "-id")
            .first()
        )
        if inbound is not None:
            break
    if inbound is None:
        return None
    return {"name": inbound.name_raw or "Без имени", "phone": inbound.phone_raw}


def complete_customer_data(data: dict) -> dict[str, str] | None:
    """Return name and phone from FSM data when both were already collected."""

    name = str(data.get("name") or "").strip()
    phone = str(data.get("phone") or "").strip()
    if name and phone:
        return {"name": name, "phone": phone}
    return None


async def question_from_message(message: Message) -> str:
    """Extract a text question or transcribe a Telegram voice message."""

    question = (message.text or "").strip()
    if not question and message.voice:
        await message.answer("Секунду, распознаю голосовое сообщение...", parse_mode=None)
        transcription = await transcribe_telegram_voice(bot=message.bot, voice=message.voice)
        if not transcription.ok:
            await message.answer(f"{transcription.error} Напишите, пожалуйста, вопрос текстом.", parse_mode=None)
            return ""
        question = transcription.text.strip()
    return question


async def create_request_from_known_customer(message: Message, *, name: str, phone: str) -> InboundRequest | None:
    """Create an intake request for a known Telegram chat without restarting the form."""

    if await sync_to_async(telegram_customer_is_blocked)(telegram_user_thread_id(message)):
        return None
    question = await question_from_message(message)
    if len(question) < 3:
        await message.answer("Напишите, пожалуйста, вопрос текстом или отправьте голосовое сообщение.", parse_mode=None)
        return None
    lead = build_lead_from_message(message, name=name, phone=phone, question=question)
    return await sync_to_async(route_telegram_customer_message)(lead)


@customer_router.message(CommandStart())
async def customer_start_handler(message: Message, state: FSMContext):
    """Start customer lead collection."""

    if await sync_to_async(telegram_customer_is_blocked)(telegram_user_thread_id(message)):
        return
    state_data = await state.get_data()
    known_customer = complete_customer_data(state_data)
    if known_customer is None:
        known_customer = await sync_to_async(existing_customer_data_for_telegram_user)(telegram_user_thread_id(message))
    if known_customer:
        await state.clear()
        await state.update_data(**known_customer)
        await state.set_state(LeadFlow.waiting_question)
        await message.answer(
            f"Здравствуйте, {known_customer['name']}! Напишите ваш вопрос. Менеджер ответит здесь.",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode=None,
        )
        return

    await state.clear()
    await state.set_state(LeadFlow.waiting_name)
    await message.answer("Здравствуйте! Я помогу оставить заявку менеджеру. Как вас называть?", reply_markup=ReplyKeyboardRemove(), parse_mode=None)


@customer_router.message(LeadFlow.waiting_name)
async def customer_name_handler(message: Message, state: FSMContext):
    """Store customer name and ask for a contact-sharing phone."""

    if await sync_to_async(telegram_customer_is_blocked)(telegram_user_thread_id(message)):
        return
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Напишите, пожалуйста, имя текстом.", parse_mode=None)
        return
    await state.update_data(name=name[:255])
    await state.set_state(LeadFlow.waiting_phone)
    await message.answer("Теперь отправьте телефон кнопкой ниже.", reply_markup=phone_keyboard(), parse_mode=None)


@customer_router.message(LeadFlow.waiting_phone)
async def customer_phone_handler(message: Message, state: FSMContext):
    """Store verified Telegram contact phone and ask for the customer's question."""

    if await sync_to_async(telegram_customer_is_blocked)(telegram_user_thread_id(message)):
        return
    if not message.contact or not message.contact.phone_number:
        await message.answer("Пожалуйста, нажмите кнопку «Отправить телефон», чтобы передать номер из Telegram.", reply_markup=phone_keyboard(), parse_mode=None)
        return
    if message.contact.user_id and message.from_user and message.contact.user_id != message.from_user.id:
        await message.answer("Нужно отправить именно ваш контакт через кнопку Telegram.", reply_markup=phone_keyboard(), parse_mode=None)
        return

    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(LeadFlow.waiting_question)
    await message.answer("Спасибо. Теперь напишите ваш вопрос или что вас интересует.", reply_markup=ReplyKeyboardRemove(), parse_mode=None)


@customer_router.message(LeadFlow.waiting_question)
async def customer_question_handler(message: Message, state: FSMContext):
    """Store the customer's question and create an intake request."""

    if await sync_to_async(telegram_customer_is_blocked)(telegram_user_thread_id(message)):
        return
    question = await question_from_message(message)
    if len(question) < 3:
        await message.answer("Напишите, пожалуйста, вопрос текстом или отправьте голосовое сообщение.", parse_mode=None)
        return

    data = await state.get_data()
    lead = build_lead_from_message(
        message,
        name=data.get("name", "Без имени"),
        phone=data.get("phone", ""),
        question=question,
    )
    await sync_to_async(route_telegram_customer_message)(lead)
    await state.update_data(name=lead.name, phone=lead.phone)
    await state.set_state(LeadFlow.waiting_question)


@customer_router.message()
async def customer_fallback_handler(message: Message):
    """Guide non-admin users into the customer flow without exposing admin commands."""

    if await sync_to_async(telegram_customer_is_blocked)(telegram_user_thread_id(message)):
        return
    known_customer = await sync_to_async(existing_customer_data_for_telegram_user)(telegram_user_thread_id(message))
    if not known_customer:
        await message.answer("Чтобы оставить заявку, отправьте /start.", parse_mode=None)
        return

    await create_request_from_known_customer(message, name=known_customer["name"], phone=known_customer["phone"])
