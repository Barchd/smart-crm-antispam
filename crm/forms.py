"""Forms for CRM auth."""

from __future__ import annotations

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError
from django.forms import ModelForm

from .auth import get_client_ip
from .models import Client, Deal, DealComment, DealStage, LoginAttempt, RoleChoices, User
from .pipeline import validate_stage_transition
from .phones import normalize_phone


class ThrottledAuthenticationForm(AuthenticationForm):
    """Authentication form with per-username throttling."""

    throttle_message = "Слишком много неудачных попыток. Попробуйте позже."

    def clean(self):
        username = (self.data.get("username") or "").strip()
        ip_address = get_client_ip(self.request)

        if username and LoginAttempt.is_locked(username):
            LoginAttempt.record_blocked(username=username, ip_address=ip_address)
            raise ValidationError(self.throttle_message, code="throttled")

        try:
            cleaned_data = super().clean()
        except ValidationError:
            if username:
                LoginAttempt.record_failed(username=username, ip_address=ip_address)
            raise

        if username:
            LoginAttempt.record_success(username=username, ip_address=ip_address)
        return cleaned_data


class CrmUserCreateForm(UserCreationForm):
    """Head-only user creation form with role assignment."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].label = "Пароль"
        self.fields["password2"].label = "Повторите пароль"
        self.fields["password1"].help_text = "Можно указать вручную или сгенерировать кнопкой ниже."

    class Meta:
        model = User
        fields = ["username", "full_name", "role", "is_active"]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = user.role == RoleChoices.HEAD
        user.is_superuser = user.role == RoleChoices.HEAD
        if commit:
            user.save()
        return user


class CrmUserUpdateForm(ModelForm):
    """Head-only user edit form with optional password reset."""

    password1 = forms.CharField(
        label="Новый пароль",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Оставьте пустым, чтобы не менять пароль. Можно указать вручную или сгенерировать.",
    )
    password2 = forms.CharField(
        label="Повторите новый пароль",
        required=False,
        widget=forms.PasswordInput(render_value=False),
    )

    class Meta:
        model = User
        fields = ["username", "full_name", "role", "is_active"]

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 or password2:
            if password1 != password2:
                self.add_error("password2", "Пароли не совпадают.")
            elif password1:
                password_validation.validate_password(password1, self.instance)
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = user.role == RoleChoices.HEAD
        user.is_superuser = user.role == RoleChoices.HEAD
        password = self.cleaned_data.get("password1")
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user


class DealPermissionForm(ModelForm):
    """Deal edit form that enforces manager assignment permissions."""

    class Meta:
        model = Deal
        fields = ["title", "amount", "manager", "next_contact_at", "reply_draft"]

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["manager"].queryset = User.objects.filter(is_active=True, role=RoleChoices.MANAGER)
        if not getattr(user, "is_head", False):
            self.fields["manager"].disabled = True
            self.fields["manager"].required = False

    def clean_manager(self):
        manager = self.cleaned_data.get("manager")
        if not getattr(self.user, "is_head", False):
            return self.instance.manager
        return manager


class DealStageTransitionForm(forms.Form):
    """Validate a pipeline click independently from the deal edit form."""

    stage = forms.ChoiceField(choices=DealStage.choices)

    def __init__(self, *args, deal: Deal, **kwargs):
        self.deal = deal
        super().__init__(*args, **kwargs)

    def clean_stage(self):
        new_stage = self.cleaned_data["stage"]
        validate_stage_transition(current_stage=self.deal.stage, new_stage=new_stage)
        return new_stage


class ClientForm(ModelForm):
    """Client form with server-side phone normalization and duplicate guard."""

    duplicate_message = "Клиент с таким номером уже существует, обратитесь к руководителю."

    class Meta:
        model = Client
        fields = ["name", "phone_raw", "email", "source", "manager", "comment"]

    def __init__(self, *args, user, **kwargs):
        self.user = user
        self.phone_normalized = ""
        super().__init__(*args, **kwargs)
        self.fields["manager"].queryset = User.objects.filter(is_active=True, role=RoleChoices.MANAGER)
        if not getattr(user, "is_head", False):
            self.fields["manager"].disabled = True
            self.fields["manager"].required = False

    def clean_phone_raw(self):
        phone_raw = self.cleaned_data["phone_raw"]
        try:
            self.phone_normalized = normalize_phone(phone_raw)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        duplicate = Client.objects.filter(phone_normalized=self.phone_normalized)
        if self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise ValidationError(self.duplicate_message)
        return phone_raw

    def clean_manager(self):
        manager = self.cleaned_data.get("manager")
        if not getattr(self.user, "is_head", False):
            return self.user
        return manager

    def save(self, commit=True):
        client = super().save(commit=False)
        client.phone_normalized = self.phone_normalized
        if not getattr(self.user, "is_head", False):
            client.manager = self.user
        if commit:
            client.save()
        return client


class DealCreateForm(ModelForm):
    """Manual deal creation form."""

    class Meta:
        model = Deal
        fields = ["client", "title", "amount", "manager", "next_contact_at", "reply_draft"]

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["client"].queryset = Client.objects.visible_to(user)
        self.fields["manager"].queryset = User.objects.filter(is_active=True, role=RoleChoices.MANAGER)
        if not getattr(user, "is_head", False):
            self.fields["manager"].disabled = True
            self.fields["manager"].required = False

    def clean_manager(self):
        manager = self.cleaned_data.get("manager")
        if not getattr(self.user, "is_head", False):
            return self.user
        return manager


class DealCommentForm(ModelForm):
    """Add a comment to a deal."""

    class Meta:
        model = DealComment
        fields = ["text"]
        widgets = {"text": forms.Textarea(attrs={"rows": 3})}
