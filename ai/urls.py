"""AI settings URL routes."""

from __future__ import annotations

from django.urls import path

from . import views


urlpatterns = [
    path("settings/ai/", views.ai_settings_view, name="ai_settings"),
    path("settings/ai/delete/", views.ai_settings_delete, name="ai_settings_delete"),
    path("settings/ai/openai/delete/", views.ai_openai_delete, name="ai_openai_delete"),
    path("settings/ai/<int:pk>/check/", views.ai_connection_check, name="ai_connection_check"),
    path("settings/ai/<int:pk>/default/", views.ai_connection_make_default, name="ai_connection_default"),
    path("settings/ai/<int:pk>/delete/", views.ai_connection_delete, name="ai_connection_delete"),
]
