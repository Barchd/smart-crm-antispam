"""Forms for AI provider administration."""

from __future__ import annotations

from django import forms

from .models import AIAPIStyleChoices, AIConnectionTypeChoices, AIProviderChoices, AISettings


OPENAI_OFFICIAL_BASE_URL = "https://api.openai.com/v1"


class AISettingsForm(forms.ModelForm):
    """Head-only form with a write-only OpenAI key field."""

    openai_api_key_input = forms.CharField(
        label="OpenAI API key",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Оставьте пустым, чтобы сохранить текущий ключ. Значение обратно не показывается.",
    )

    class Meta:
        model = AISettings
        fields = [
            "name",
            "connection_type",
            "ollama_url",
            "ollama_model",
            "openai_base_url",
            "openai_model",
            "openai_api_style",
            "openai_transcription_model",
        ]
        labels = {
            "name": "Название подключения",
            "connection_type": "Тип подключения",
            "ollama_url": "Ollama URL",
            "ollama_model": "Ollama model",
            "openai_base_url": "OpenAI base URL",
            "openai_model": "OpenAI model",
            "openai_api_style": "API style",
            "openai_transcription_model": "OpenAI transcription model",
        }
        widgets = {
            "openai_base_url": forms.URLInput(attrs={"placeholder": "https://api.openai.com/v1"}),
            "openai_model": forms.TextInput(attrs={"placeholder": "gpt-5.6-sol"}),
            "openai_transcription_model": forms.TextInput(attrs={"placeholder": "gpt-transcribe"}),
        }
        help_texts = {
            "ollama_url": "Например: http://127.0.0.1:11434",
            "openai_model": "Актуальный основной placeholder: gpt-5.6-sol. Для экономии можно выбрать gpt-5.6-terra или gpt-5.6-luna.",
            "openai_transcription_model": "Актуальный placeholder для распознавания речи: gpt-transcribe.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ollama_url"].required = False
        self.fields["ollama_model"].required = False
        self.fields["openai_base_url"].required = False
        self.fields["openai_model"].required = False
        self.fields["openai_api_style"].required = False
        self.fields["openai_transcription_model"].required = False
        self.fields["connection_type"].choices = AIConnectionTypeChoices.choices
        self.fields["openai_api_style"].choices = [
            (AIAPIStyleChoices.CHAT_COMPLETIONS, "Chat Completions -> /chat/completions"),
            (AIAPIStyleChoices.RESPONSES, "Responses -> /responses"),
        ]
        for field_name, field in self.fields.items():
            css_class = "form-select" if field_name in {"connection_type", "openai_api_style"} else "form-control"
            field.widget.attrs["class"] = css_class

    def clean(self):
        cleaned_data = super().clean()
        connection_type = cleaned_data.get("connection_type")
        api_key = self.cleaned_data.get("openai_api_key_input", "").strip()
        has_existing_key = bool(getattr(self.instance, "openai_api_key", ""))

        if connection_type == AIConnectionTypeChoices.OLLAMA:
            self._require("ollama_url", "Ollama URL обязателен для локального подключения.")
            self._require("ollama_model", "Model обязателен для локального подключения.")
            cleaned_data["openai_api_style"] = AIAPIStyleChoices.OLLAMA
            return cleaned_data

        if connection_type == AIConnectionTypeChoices.OPENAI_OFFICIAL:
            if not cleaned_data.get("openai_base_url"):
                cleaned_data["openai_base_url"] = OPENAI_OFFICIAL_BASE_URL
            self._require("openai_model", "Model обязателен для OpenAI official.")
            if not api_key and not has_existing_key:
                self.add_error("openai_api_key_input", "API key обязателен для нового OpenAI-подключения.")
            cleaned_data["openai_api_style"] = AIAPIStyleChoices.CHAT_COMPLETIONS
            return cleaned_data

        if connection_type == AIConnectionTypeChoices.OPENAI_COMPATIBLE:
            self._require("openai_base_url", "Base URL обязателен для custom bridge/proxy.")
            self._require("openai_model", "Model обязателен для custom bridge/proxy.")
            api_style = cleaned_data.get("openai_api_style")
            if api_style not in (AIAPIStyleChoices.CHAT_COMPLETIONS, AIAPIStyleChoices.RESPONSES):
                self.add_error("openai_api_style", "Выберите API style для custom bridge/proxy.")
            if not api_key and not has_existing_key:
                self.add_error("openai_api_key_input", "API key обязателен для нового custom bridge/proxy подключения.")
            return cleaned_data

        self.add_error("connection_type", "Неизвестный тип подключения.")
        return cleaned_data

    def _require(self, field_name: str, message: str) -> None:
        if not self.cleaned_data.get(field_name):
            self.add_error(field_name, message)

    def save(self, commit=True, *, user=None):
        instance = super().save(commit=False)
        connection_type = self.cleaned_data["connection_type"]
        if not instance.pk and not AISettings.objects.filter(is_default=True).exists():
            instance.is_default = True
        if connection_type == AIConnectionTypeChoices.OLLAMA:
            instance.provider = AIProviderChoices.OLLAMA
            instance.openai_api_style = AIAPIStyleChoices.OLLAMA
        else:
            instance.provider = AIProviderChoices.OPENAI
            if connection_type == AIConnectionTypeChoices.OPENAI_OFFICIAL:
                instance.openai_base_url = OPENAI_OFFICIAL_BASE_URL
                instance.openai_api_style = AIAPIStyleChoices.CHAT_COMPLETIONS

        api_key = self.cleaned_data.get("openai_api_key_input", "").strip()
        if api_key:
            instance.openai_api_key = api_key
        if user is not None:
            instance.updated_by = user
        if commit:
            instance.save()
        return instance
