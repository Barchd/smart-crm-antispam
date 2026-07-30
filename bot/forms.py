"""Forms for Telegram chat-bot settings."""

from __future__ import annotations

from django import forms

from .models import BotSettings


class BotSettingsForm(forms.ModelForm):
    """Head-only form with a write-only Telegram bot token."""

    bot_token_input = forms.CharField(
        label="Telegram bot token",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Оставьте пустым, чтобы сохранить текущий token. Значение обратно не показывается.",
    )

    class Meta:
        model = BotSettings
        fields = ["admin_chat_id", "admin_telegram_ids"]
        labels = {
            "admin_chat_id": "Admin chat/user id",
            "admin_telegram_ids": "Allowed Telegram user ids",
        }
        widgets = {
            "admin_telegram_ids": forms.Textarea(attrs={"rows": 3}),
        }

    def save(self, commit=True, *, user=None):
        instance = super().save(commit=False)
        token = self.cleaned_data.get("bot_token_input", "").strip()
        if token:
            instance.bot_token = token
        if user is not None:
            instance.updated_by = user
        if commit:
            instance.save()
        return instance


class CustomerPromptSettingsForm(forms.ModelForm):
    """Independent head-only form for customer bot AI guidance."""

    class Meta:
        model = BotSettings
        fields = ["customer_prompt"]
        labels = {"customer_prompt": "Промпт клиентского чат-бота"}
        help_texts = {
            "customer_prompt": (
                "Задаёт тон, формат и сценарий ответа. Факты о салоне, ценах и автомобилях "
                "подставляются автоматически из базы знаний. Пустое поле допустимо."
            )
        }
        widgets = {
            "customer_prompt": forms.Textarea(
                attrs={
                    "rows": 9,
                    "placeholder": (
                        "Например: отвечай кратко и доброжелательно; не повторяй приветствие; "
                        "уточняй бюджет, модель и срок покупки; используй ссылки только из базы знаний."
                    ),
                }
            ),
        }

    def save(self, commit=True, *, user=None):
        instance = super().save(commit=False)
        if user is not None:
            instance.updated_by = user
        if commit:
            instance.save()
        return instance
