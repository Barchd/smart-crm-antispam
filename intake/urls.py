"""Intake URL routes."""

from __future__ import annotations

from django.urls import path

from . import views


urlpatterns = [
    path("lead/", views.lead_form, name="lead_form"),
    path("settings/webhook/", views.webhook_settings_view, name="webhook_settings"),
]
