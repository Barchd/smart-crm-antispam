"""Head-only Telegram bot settings views."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from crm.access import is_head

from .config import check_bot_connection, get_bot_config, mask_secret
from .forms import BotSettingsForm, CustomerPromptSettingsForm
from .models import BotSettings


@login_required
def bot_settings_view(request):
    """Allow a head user to configure Telegram bot settings."""

    if not is_head(request.user):
        raise PermissionDenied

    settings_obj = BotSettings.current()
    form = BotSettingsForm(instance=settings_obj)
    customer_prompt_form = CustomerPromptSettingsForm(instance=settings_obj)
    if request.method == "POST":
        action = request.POST.get("action", "save_transport")
        if action == "save_customer_prompt":
            customer_prompt_form = CustomerPromptSettingsForm(request.POST, instance=settings_obj)
            if customer_prompt_form.is_valid():
                customer_prompt_form.save(user=request.user)
                messages.success(request, "Промпт клиентского чат-бота сохранён")
                return redirect("bot_settings")
        else:
            form = BotSettingsForm(request.POST, instance=settings_obj)
            if form.is_valid():
                settings_obj = form.save(user=request.user)
                if action == "check_transport":
                    result = check_bot_connection(get_bot_config())
                    if result.ok:
                        messages.success(request, result.message)
                    else:
                        messages.error(request, result.message)
                else:
                    messages.success(request, "Настройки Telegram transport сохранены")
                return redirect("bot_settings")

    return render(
        request,
        "bot/settings.html",
        {
            "form": form,
            "customer_prompt_form": customer_prompt_form,
            "settings_obj": settings_obj,
            "bot_token_mask": mask_secret(settings_obj.bot_token),
        },
    )
