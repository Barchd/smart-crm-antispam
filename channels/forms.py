"""Forms for customer messaging UI."""

from __future__ import annotations

from django import forms

from .models import Dialog


class SendMessageForm(forms.Form):
    """Editable manager-approved outbound message form."""

    dialog = forms.ModelChoiceField(queryset=Dialog.objects.none(), label="Канал")
    text = forms.CharField(label="Предложенный ответ", widget=forms.Textarea(attrs={"rows": 4}))

    def __init__(self, *args, dialogs, initial_text: str = "", default_dialog: Dialog | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["dialog"].queryset = dialogs
        self.fields["text"].initial = initial_text
        if default_dialog is not None:
            self.fields["dialog"].initial = default_dialog


class RegenerateReplyForm(forms.Form):
    """Manager prompt for generating a new editable reply draft."""

    prompt = forms.CharField(
        label="Промпт для нового варианта ответа",
        help_text="Например: отвечай короче, уточни бюджет и предложи тест-драйв.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
