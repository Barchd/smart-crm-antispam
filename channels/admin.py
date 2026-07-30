"""Django admin registration for customer messaging."""

from django.contrib import admin

from .models import Channel, DeliveryLog, Dialog, Message


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    """Inspect channels."""

    list_display = ("name", "type", "is_active", "updated_at")
    list_filter = ("type", "is_active")


@admin.register(Dialog)
class DialogAdmin(admin.ModelAdmin):
    """Inspect customer dialogs."""

    list_display = ("channel", "client", "deal", "external_thread_id", "last_message_at")
    list_filter = ("channel__type",)
    search_fields = ("external_thread_id", "client__name", "deal__title")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    """Inspect dialog messages."""

    list_display = ("dialog", "direction", "status", "sent_by", "created_at")
    list_filter = ("direction", "status")


@admin.register(DeliveryLog)
class DeliveryLogAdmin(admin.ModelAdmin):
    """Inspect outbound delivery attempts."""

    list_display = ("message", "adapter", "status", "created_at")
    list_filter = ("adapter", "status")
