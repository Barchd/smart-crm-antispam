"""Root URL configuration."""

from django.contrib import admin
from django.urls import include, path

from crm.api import api

urlpatterns = [
    path("", include("crm.urls")),
    path("", include("intake.urls")),
    path("", include("ai.urls")),
    path("", include("bot.urls")),
    path("api/v1/", api.urls),
    path("admin/", admin.site.urls),
]
