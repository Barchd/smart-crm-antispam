"""Bot settings URL routes."""

from __future__ import annotations

from django.urls import path

from . import views


urlpatterns = [
    path("settings/bot/", views.bot_settings_view, name="bot_settings"),
]
