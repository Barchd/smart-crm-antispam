"""CRM URL routes."""

from __future__ import annotations

from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeDoneView, PasswordChangeView
from django.urls import path

from .forms import ThrottledAuthenticationForm
from . import views


urlpatterns = [
    path("", views.root_redirect, name="root"),
    path("login/", LoginView.as_view(template_name="registration/login.html", authentication_form=ThrottledAuthenticationForm), name="login"),
    path("logout/", LogoutView.as_view(next_page="login"), name="logout"),
    path("password/change/", PasswordChangeView.as_view(template_name="registration/password_change_form.html"), name="password_change"),
    path("password/change/done/", PasswordChangeDoneView.as_view(template_name="registration/password_change_done.html"), name="password_change_done"),
    path("users/", views.users_index, name="users"),
    path("users/new/", views.user_create, name="user_create"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/delete/", views.user_delete, name="user_delete"),
    path("clients/", views.clients_index, name="clients"),
    path("clients/new/", views.client_create, name="client_create"),
    path("clients/<int:pk>/edit/", views.client_edit, name="client_edit"),
    path("deals/", views.deals_index, name="deals"),
    path("deals/new/", views.deal_create, name="deal_create"),
    path("deals/<int:pk>/", views.deal_detail, name="deal_detail"),
    path("deals/<int:pk>/stage/", views.deal_stage_change, name="deal_stage_change"),
    path("deals/<int:pk>/edit/", views.deal_edit, name="deal_edit"),
    path("deals/<int:pk>/delete/", views.deal_delete, name="deal_delete"),
    path("deals/<int:pk>/comments/", views.deal_comment_add, name="deal_comment_add"),
    path("deals/<int:pk>/approve-reply/", views.deal_reply_approve, name="deal_reply_approve"),
    path("deals/<int:pk>/regenerate-reply/", views.deal_reply_regenerate, name="deal_reply_regenerate"),
    path("deals/<int:pk>/send-message/", views.deal_message_send, name="deal_message_send"),
    path("requests/", views.inbound_requests_index, name="inbound_requests"),
    path("requests/<int:pk>/retry/", views.inbound_request_retry, name="inbound_request_retry"),
    path("requests/<int:pk>/not-spam/", views.inbound_request_not_spam, name="inbound_request_not_spam"),
    path("requests/<int:pk>/spam/", views.inbound_request_spam, name="inbound_request_spam"),
    path("requests/<int:pk>/delete/", views.inbound_request_delete, name="inbound_request_delete"),
]
