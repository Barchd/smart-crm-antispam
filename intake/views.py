"""Views for internal intake form and webhook settings."""

from __future__ import annotations

import secrets
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from crm.access import is_head

from .forms import LeadForm
from .models import InboundRequestStatus, WebhookSettings
from .services import create_inbound_request
from .webhook_config import get_webhook_secret


def lead_form(request):
    """Internal mock lead form protected by normal Django CSRF."""

    accepted = False
    if request.method == "POST":
        form = LeadForm(request.POST)
        if form.is_valid():
            payload = dict(form.cleaned_data)
            payload["external_id"] = str(uuid.uuid4())
            status = InboundRequestStatus.BLOCKED if form.cleaned_data.get("website") else None
            reason = "honeypot" if status else ""
            create_inbound_request(
                payload=payload,
                request=request,
                external_id=payload["external_id"],
                source_type="form",
                force_status=status,
                spam_reason=reason,
            )
            accepted = True
            form = LeadForm()
    else:
        form = LeadForm()
    return render(request, "intake/lead_form.html", {"form": form, "accepted": accepted})


def _mask(value: str) -> str:
    if not value:
        return ""
    tail = value[-4:] if len(value) >= 4 else "****"
    return f"***{tail}"


@login_required
def webhook_settings_view(request):
    """Head-only page: generate / rotate the HMAC webhook secret."""

    if not is_head(request.user):
        raise PermissionDenied

    settings_obj = WebhookSettings.current()
    new_secret = None  # shown once after generation

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "generate":
            new_secret = secrets.token_urlsafe(32)
            settings_obj.webhook_secret = new_secret
            settings_obj.updated_by = request.user
            settings_obj.save()
            messages.success(request, "Новый секрет сгенерирован. Скопируйте его ниже — повторно не покажем.")
            # Render directly (not redirect) so we can pass new_secret once.
            return render(
                request,
                "intake/webhook_settings.html",
                {
                    "settings_obj": settings_obj,
                    "secret_mask": _mask(settings_obj.webhook_secret),
                    "new_secret": new_secret,
                },
            )
        return redirect("webhook_settings")

    return render(
        request,
        "intake/webhook_settings.html",
        {
            "settings_obj": settings_obj,
            "secret_mask": _mask(settings_obj.webhook_secret),
            "new_secret": None,
        },
    )
