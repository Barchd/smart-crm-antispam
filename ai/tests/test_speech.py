from __future__ import annotations

from unittest.mock import Mock, patch

import httpx
from django.test import TestCase

from ai.models import AIProviderChoices, AISettings
from ai.speech import transcribe_audio_bytes


class SpeechToTextTests(TestCase):
    def test_transcription_requires_openai_provider(self):
        AISettings.objects.create(pk=1, provider=AIProviderChoices.OLLAMA, openai_api_key="")

        result = transcribe_audio_bytes(audio=b"voice")

        self.assertFalse(result.ok)
        self.assertIn("OpenAI", result.error)

    def test_transcription_posts_audio_without_leaking_key(self):
        AISettings.objects.create(
            pk=1,
            provider=AIProviderChoices.OPENAI,
            openai_base_url="https://api.openai.test/v1",
            openai_model="chat-model",
            openai_transcription_model="transcribe-test",
            openai_api_key="sk-secret",
        )
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"text": "Хочу купить автомобиль"}

        with patch("ai.speech.httpx.post", return_value=response) as post:
            result = transcribe_audio_bytes(audio=b"voice-bytes", filename="voice.ogg")

        self.assertTrue(result.ok)
        self.assertEqual(result.text, "Хочу купить автомобиль")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["data"]["model"], "transcribe-test")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-secret")
        self.assertEqual(kwargs["files"]["file"][0], "voice.ogg")

    def test_transcription_error_sanitizes_key(self):
        AISettings.objects.create(
            pk=1,
            provider=AIProviderChoices.OPENAI,
            openai_api_key="sk-secret",
        )

        with patch("ai.speech.httpx.post", side_effect=httpx.ConnectError("boom sk-secret")):
            result = transcribe_audio_bytes(audio=b"voice")

        self.assertFalse(result.ok)
        self.assertNotIn("sk-secret", result.error)
