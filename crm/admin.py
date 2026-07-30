"""CRM admin registration."""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Client, Deal, DealComment, DealLog, LoginAttempt, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Admin view for CRM users."""

    model = User
    list_display = ("username", "full_name", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active")
    search_fields = ("username", "full_name")
    ordering = ("full_name", "username")
    fieldsets = DjangoUserAdmin.fieldsets + ((None, {"fields": ("role", "full_name")}),)
    add_fieldsets = DjangoUserAdmin.add_fieldsets + ((None, {"fields": ("role", "full_name")}),)


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    """Audit log for auth attempts."""

    list_display = ("username", "result", "attempted_at", "ip_address")
    list_filter = ("result", "attempted_at")
    search_fields = ("username", "ip_address")
    ordering = ("-attempted_at",)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    """Admin view for clients."""

    list_display = ("name", "phone_normalized", "email", "source", "manager", "created_at")
    list_filter = ("source", "manager")
    search_fields = ("name", "phone_raw", "phone_normalized", "email")
    ordering = ("name", "id")


@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    """Admin view for deals."""

    list_display = ("title", "client", "amount", "stage", "manager", "next_contact_at", "created_at")
    list_filter = ("stage", "manager", "risk_flagged", "created_without_ai")
    search_fields = ("title", "client__name", "client__phone_normalized")
    ordering = ("-created_at", "-id")


@admin.register(DealLog)
class DealLogAdmin(admin.ModelAdmin):
    """Admin view for deal logs."""

    list_display = ("deal", "action", "user", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("deal__title", "old_value", "new_value")
    ordering = ("-created_at", "-id")


@admin.register(DealComment)
class DealCommentAdmin(admin.ModelAdmin):
    """Admin view for deal comments."""

    list_display = ("deal", "author", "created_at")
    search_fields = ("deal__title", "text")
    ordering = ("-created_at", "-id")
