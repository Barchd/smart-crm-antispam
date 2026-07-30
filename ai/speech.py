"""Speech-to-text helpers for customer voice messages."""

from __future__ import annotations

from dataclasses import dataclass

import re

import httpx
from aiogram import Bot
from aiogram.types import Voice
from asgiref.sync import sync_to_async

from .config import get_ai_provider_config
from .models import AIProviderChoices


@dataclass(frozen=True)
class TranscriptionResult:
    """Safe user-facing transcription result."""

    ok: bool
    text: str = ""
    error: str = ""


def transcribe_audio_bytes(*, audio: bytes, filename: str = "voice.ogg", timeout: float = 60.0) -> TranscriptionResult:
    """Transcribe audio through the configured OpenAI-compatible provider."""

    config = get_ai_provider_config()
    if config.provider != AIProviderChoices.OPENAI:
        return TranscriptionResult(ok=False, error="Распознавание голосовых сообщений доступно только при provider OpenAI.")
    if not config.openai_api_key:
        return TranscriptionResult(ok=False, error="OpenAI API key не задан в настройках AI.")
    if not audio:
        return TranscriptionResult(ok=False, error="Голосовое сообщение пустое.")

    try:
        response = httpx.post(
            f"{config.openai_base_url.rstrip('/')}/audio/transcriptions",
            headers={"Authorization": f"Bearer {config.openai_api_key}"},
            data={"model": config.openai_transcription_model, "language": "ru"},
            files={"file": (filename, audio, "audio/ogg")},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        sanitized = re.sub(re.escape(config.openai_api_key), "***", str(exc))
        return TranscriptionResult(ok=False, error=f"Не удалось распознать голосовое сообщение: {sanitized}")

    text = str(payload.get("text") or "").strip() if isinstance(payload, dict) else ""
    if not text:
        return TranscriptionResult(ok=False, error="Распознавание вернуло пустой текст.")
    return TranscriptionResult(ok=True, text=text)


async def transcribe_telegram_voice(*, bot: Bot, voice: Voice) -> TranscriptionResult:
    """Download a Telegram voice message and transcribe it."""

    if voice.duration and voice.duration > 120:
        return TranscriptionResult(ok=False, error="Голосовое сообщение слишком длинное. Максимум 2 минуты.")
    if voice.file_size and voice.file_size > 10 * 1024 * 1024:
        return TranscriptionResult(ok=False, error="Голосовое сообщение слишком большое. Максимум 10 МБ.")

    telegram_file = await bot.get_file(voice.file_id)
    stream = await bot.download_file(telegram_file.file_path)
    audio = stream.read()
    return await sync_to_async(transcribe_audio_bytes)(audio=audio, filename=f"{voice.file_id}.ogg")
