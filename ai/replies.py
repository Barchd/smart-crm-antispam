"""AI-assisted reply draft generation for CRM dialogs."""

from __future__ import annotations

from dataclasses import dataclass

from channels.models import Dialog, MessageDirection
from crm.models import Deal

from .client import AIModelUnavailable, create_ai_client


@dataclass(frozen=True)
class ReplyDraftResult:
    """Generated editable reply draft."""

    text: str


@dataclass(frozen=True)
class ReplyDraftInput:
    """Minimal object accepted by the existing AI client prompt builder."""

    id: int
    source_type: str
    source_name: str
    message_text: str
    name_raw: str
    phone_raw: str
    email_raw: str
    is_follow_up: bool


def build_reply_context(*, deal: Deal, dialog: Dialog, manager_prompt: str) -> str:
    """Build bounded context for a new manager-approved reply draft."""

    messages = []
    for message in dialog.messages.order_by("-created_at", "-id")[:12]:
        direction = "клиент" if message.direction == MessageDirection.INBOUND else "менеджер"
        messages.append(f"{direction}: {message.text[:1000]}")
    messages.reverse()
    history = "\n".join(messages) or "История сообщений пока пустая."
    current_draft = (deal.reply_draft or "").strip() or "Текущий черновик пока пустой."
    base = (
        "Сформируй новый вариант ответа клиенту для автосалона. "
        "Это только черновик: не отправляй его и не обещай действий вне CRM.\n\n"
        f"Сделка: {deal.title}\n"
        f"Клиент: {deal.client.name}\n"
        f"Канал: {dialog.channel.get_type_display()} / {dialog.channel.name}\n\n"
        f"История чата:\n{history}\n\n"
        f"Текущий предложенный ответ, который нужно учитывать и доработать:\n{current_draft[:1200]}\n\n"
        f"Пожелание менеджера к ответу:\n{manager_prompt.strip()}"
    )
    return base[:6000]


def generate_reply_draft(*, deal: Deal, dialog: Dialog, manager_prompt: str, client=None) -> ReplyDraftResult:
    """Generate and return a new reply draft without sending it."""

    prompt = manager_prompt.strip()
    if not prompt:
        raise AIModelUnavailable("Промпт не может быть пустым")
    if dialog.deal_id != deal.id:
        raise AIModelUnavailable("Диалог не относится к сделке")

    inbound = ReplyDraftInput(
        id=deal.inbound_request_id or deal.id,
        source_type=dialog.channel.type,
        source_name=dialog.channel.name,
        message_text=build_reply_context(deal=deal, dialog=dialog, manager_prompt=prompt),
        name_raw=deal.client.name,
        phone_raw=deal.client.phone_raw,
        email_raw=deal.client.email,
        is_follow_up=dialog.messages.filter(direction=MessageDirection.OUTBOUND).exists(),
    )
    analysis = (client or create_ai_client()).analyze(inbound=inbound)
    return ReplyDraftResult(text=analysis.suggested_reply)
