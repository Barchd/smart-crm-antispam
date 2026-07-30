"""Django app config for customer messaging."""

from django.apps import AppConfig


class ChannelsConfig(AppConfig):
    """Application containing channel-agnostic customer messaging models."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "channels"
    verbose_name = "Customer messaging"
