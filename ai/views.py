"""Head-only AI settings views."""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from crm.access import is_head

from .config import (
    AIProviderConfig,
    check_ai_connection,
    check_openai_chat_model_connection,
    check_openai_model_list_access,
    check_openai_responses_model_connection,
    mask_secret,
    record_ai_connection_check,
)
from .forms import AISettingsForm
from .models import AIAPIStyleChoices, AIConnectionStatusChoices, AIConnectionTypeChoices, AIProviderChoices, AISettings


@login_required
def ai_settings_view(request):
    """Allow a head user to configure provider and check connectivity."""

    if not is_head(request.user):
        raise PermissionDenied

    default_connection = AISettings.current()
    edit_connection = _get_edit_connection(request)
    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "check_current":
            result = check_ai_connection(_config_from_settings(default_connection))
            _record_and_flash_check(request, default_connection, result)
            return redirect("ai_settings")
        if action == "check_openai":
            result = check_ai_connection(_openai_config(default_connection))
            _record_and_flash_check(request, default_connection, result)
            return redirect("ai_settings")
        if action == "check_openai_model":
            model = (request.POST.get("openai_check_model") or "").strip()
            check_kind = request.POST.get("openai_check_kind", "chat")
            config = _openai_config(default_connection)
            if check_kind == "list":
                result = check_openai_model_list_access(
                    base_url=config.openai_base_url,
                    model=model,
                    api_key=config.openai_api_key,
                )
            elif check_kind == "responses":
                result = check_openai_responses_model_connection(
                    base_url=config.openai_base_url,
                    model=model,
                    api_key=config.openai_api_key,
                )
            else:
                result = check_openai_chat_model_connection(
                    base_url=config.openai_base_url,
                    model=model,
                    api_key=config.openai_api_key,
                )
            _record_and_flash_check(request, default_connection, result)
            return redirect("ai_settings")

        post_connection = _get_post_connection(request)
        form = AISettingsForm(request.POST, instance=post_connection)
        if form.is_valid():
            saved_connection = form.save(user=request.user)
            if action == "check":
                result = check_ai_connection(_config_from_settings(saved_connection))
                _record_and_flash_check(request, saved_connection, result)
            else:
                messages.success(request, "AI-подключение сохранено")
            return redirect("ai_settings")
    else:
        form = AISettingsForm(instance=edit_connection)

    return render(
        request,
        "ai/settings.html",
        {
            "form": form,
            "settings_obj": default_connection,
            "connections": AISettings.objects.order_by("-is_default", "connection_type", "name", "pk"),
            "edit_connection": edit_connection,
            "openai_key_mask": mask_secret(edit_connection.openai_api_key) if edit_connection else "",
            "connection_types": AIConnectionTypeChoices,
            "api_styles": AIAPIStyleChoices,
            "check_statuses": AIConnectionStatusChoices,
        },
    )


@login_required
def ai_settings_delete(request):
    """Delete saved AI settings and fall back to env/default values."""

    if not is_head(request.user):
        raise PermissionDenied
    if request.method != "POST":
        raise PermissionDenied

    deleted_count, _ = AISettings.objects.filter(pk=1).delete()
    if deleted_count:
        messages.success(request, "Сохраненное AI-подключение удалено. Используются значения по умолчанию/env fallback.")
    else:
        messages.info(request, "Сохраненное AI-подключение уже отсутствует.")
    return redirect("ai_settings")


@login_required
def ai_connection_check(request, pk: int):
    """Check one saved AI connection."""

    if not is_head(request.user):
        raise PermissionDenied
    if request.method != "POST":
        raise PermissionDenied

    connection = get_object_or_404(AISettings, pk=pk)
    model = (request.POST.get("openai_check_model") or "").strip()
    check_kind = request.POST.get("openai_check_kind", "active")
    if model and connection.provider == AIProviderChoices.OPENAI:
        if check_kind == "list":
            result = check_openai_model_list_access(
                base_url=connection.openai_base_url,
                model=model,
                api_key=connection.openai_api_key,
            )
        elif check_kind == "responses":
            result = check_openai_responses_model_connection(
                base_url=connection.openai_base_url,
                model=model,
                api_key=connection.openai_api_key,
            )
        else:
            result = check_openai_chat_model_connection(
                base_url=connection.openai_base_url,
                model=model,
                api_key=connection.openai_api_key,
            )
    else:
        result = check_ai_connection(_config_from_settings(connection))
    _record_and_flash_check(request, connection, result)
    return redirect("ai_settings")


@login_required
def ai_connection_make_default(request, pk: int):
    """Set one saved AI connection as the runtime default."""

    if not is_head(request.user):
        raise PermissionDenied
    if request.method != "POST":
        raise PermissionDenied

    connection = get_object_or_404(AISettings, pk=pk)
    connection.make_default()
    messages.success(request, f"Подключение «{connection.name}» назначено по умолчанию")
    return redirect("ai_settings")


@login_required
def ai_connection_delete(request, pk: int):
    """Delete one saved AI connection and keep a default available."""

    if not is_head(request.user):
        raise PermissionDenied
    if request.method != "POST":
        raise PermissionDenied

    connection = get_object_or_404(AISettings, pk=pk)
    name = connection.name
    was_default = connection.is_default
    connection.delete()
    if was_default:
        replacement = AISettings.objects.order_by("pk").first()
        if replacement:
            replacement.make_default()
        else:
            AISettings.current()
    messages.success(request, f"Подключение «{name}» удалено")
    return redirect("ai_settings")


@login_required
def ai_openai_delete(request):
    """Clear OpenAI credentials/config without deleting Ollama settings."""

    if not is_head(request.user):
        raise PermissionDenied
    if request.method != "POST":
        raise PermissionDenied

    settings_obj = AISettings.current()
    if settings_obj.provider == AIProviderChoices.OPENAI:
        settings_obj.provider = AIProviderChoices.OLLAMA
    settings_obj.connection_type = AIConnectionTypeChoices.OLLAMA
    settings_obj.openai_api_key = ""
    settings_obj.openai_base_url = settings.OPENAI_BASE_URL
    settings_obj.openai_model = settings.OPENAI_MODEL
    settings_obj.openai_transcription_model = settings.OPENAI_TRANSCRIPTION_MODEL
    settings_obj.openai_api_style = AIAPIStyleChoices.CHAT_COMPLETIONS
    settings_obj.last_check_status = AIConnectionStatusChoices.UNKNOWN
    settings_obj.last_check_message = ""
    settings_obj.last_checked_at = None
    settings_obj.updated_by = request.user
    settings_obj.save()
    messages.success(request, "OpenAI-подключение удалено. Активный provider переключен на Ollama, если был выбран OpenAI.")
    return redirect("ai_settings")


def _get_edit_connection(request) -> AISettings | None:
    edit_id = request.GET.get("edit")
    if not edit_id:
        return None
    return get_object_or_404(AISettings, pk=edit_id)


def _get_post_connection(request) -> AISettings | None:
    connection_id = request.POST.get("connection_id")
    if not connection_id:
        return None
    return get_object_or_404(AISettings, pk=connection_id)


def _openai_config(settings_obj: AISettings) -> AIProviderConfig:
    """Build an OpenAI config from saved settings regardless of active provider."""

    return AIProviderConfig(
        provider=AIProviderChoices.OPENAI,
        connection_type=settings_obj.connection_type,
        ollama_url=settings_obj.ollama_url,
        ollama_model=settings_obj.ollama_model,
        openai_base_url=settings_obj.openai_base_url,
        openai_model=settings_obj.openai_model,
        openai_api_style=settings_obj.openai_api_style,
        openai_transcription_model=settings_obj.openai_transcription_model,
        openai_api_key=settings_obj.openai_api_key,
    )


def _config_from_settings(settings_obj: AISettings) -> AIProviderConfig:
    """Build runtime config from saved settings, without env fallback side effects."""

    return AIProviderConfig(
        provider=settings_obj.provider,
        connection_type=settings_obj.connection_type,
        ollama_url=settings_obj.ollama_url,
        ollama_model=settings_obj.ollama_model,
        openai_base_url=settings_obj.openai_base_url,
        openai_model=settings_obj.openai_model,
        openai_api_style=settings_obj.openai_api_style,
        openai_transcription_model=settings_obj.openai_transcription_model,
        openai_api_key=settings_obj.openai_api_key,
    )


def _record_and_flash_check(request, settings_obj: AISettings, result) -> None:
    """Persist and display a provider check result."""

    record_ai_connection_check(settings_obj, result)
    if result.ok:
        messages.success(request, result.message)
    else:
        messages.error(request, result.message)
