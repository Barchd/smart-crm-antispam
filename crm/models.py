"""CRM domain models."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.conf import settings
from django.db import models
from django.utils import timezone


class RoleChoices(models.TextChoices):
    """Supported CRM roles."""

    MANAGER = "manager", "Менеджер"
    HEAD = "head", "Руководитель"


class UserManager(BaseUserManager):
    """Custom user manager for the CRM account model."""

    use_in_migrations = True

    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError("The username must be set")
        if not extra_fields.get("full_name"):
            raise ValueError("The full_name must be set")

        user = self.model(username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault("role", RoleChoices.HEAD)
        extra_fields.setdefault("full_name", username)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(username, password, **extra_fields)


class User(AbstractUser):
    """CRM user with role and display name."""

    objects = UserManager()

    role = models.CharField(max_length=16, choices=RoleChoices.choices, default=RoleChoices.MANAGER)
    full_name = models.CharField(max_length=255)

    class Meta:
        ordering = ["full_name", "username"]

    def __str__(self) -> str:
        return self.full_name or self.username

    @property
    def is_head(self) -> bool:
        return self.role == RoleChoices.HEAD

    @property
    def is_manager(self) -> bool:
        return self.role == RoleChoices.MANAGER


class LoginAttemptResult(models.TextChoices):
    """Outcome of one login attempt."""

    SUCCESS = "success", "Успешно"
    FAILED = "failed", "Неуспешно"
    BLOCKED = "blocked", "Заблокировано"


class LoginAttempt(models.Model):
    """Audit trail for login attempts and throttle source."""

    username = models.CharField(max_length=150, db_index=True)
    result = models.CharField(max_length=16, choices=LoginAttemptResult.choices, db_index=True)
    attempted_at = models.DateTimeField(default=timezone.now, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-attempted_at"]
        indexes = [
            models.Index(fields=["username", "result", "attempted_at"]),
        ]

    @staticmethod
    def normalize_username(username: str) -> str:
        return username.strip().casefold()

    @classmethod
    def window_start(cls):
        return timezone.now() - timedelta(minutes=settings.LOGIN_ATTEMPT_WINDOW_MINUTES)

    @classmethod
    def failure_count(cls, username: str, *, ip_address: str | None = None) -> int:
        attempts = cls.objects.filter(username=cls.normalize_username(username), attempted_at__gte=cls.window_start())
        attempts = attempts.filter(ip_address__isnull=True) if ip_address is None else attempts.filter(ip_address=ip_address)
        last_success = attempts.filter(result=LoginAttemptResult.SUCCESS).order_by("-attempted_at").first()
        failures = attempts.filter(result=LoginAttemptResult.FAILED)
        if last_success:
            failures = failures.filter(attempted_at__gt=last_success.attempted_at)
        return failures.count()

    @classmethod
    def is_locked(cls, username: str, *, ip_address: str | None = None) -> bool:
        return cls.failure_count(username, ip_address=ip_address) >= settings.LOGIN_MAX_ATTEMPTS

    @classmethod
    def record_success(cls, username: str, *, ip_address: str | None = None) -> None:
        cls.objects.create(
            username=cls.normalize_username(username),
            result=LoginAttemptResult.SUCCESS,
            ip_address=ip_address,
        )

    @classmethod
    def record_failed(cls, username: str, *, ip_address: str | None = None) -> None:
        cls.objects.create(
            username=cls.normalize_username(username),
            result=LoginAttemptResult.FAILED,
            ip_address=ip_address,
        )

    @classmethod
    def record_blocked(cls, username: str, *, ip_address: str | None = None) -> None:
        cls.objects.create(
            username=cls.normalize_username(username),
            result=LoginAttemptResult.BLOCKED,
            ip_address=ip_address,
        )


class ClientQuerySet(models.QuerySet):
    """Visibility rules for clients."""

    def visible_to(self, user):
        if not getattr(user, "is_authenticated", False):
            return self.none()
        if getattr(user, "role", None) == RoleChoices.HEAD:
            return self.all()
        if getattr(user, "role", None) == RoleChoices.MANAGER:
            return self.filter(manager=user)
        return self.none()


class Client(models.Model):
    """Customer card."""

    objects = ClientQuerySet.as_manager()

    name = models.CharField(max_length=255)
    phone_raw = models.CharField(max_length=64)
    phone_normalized = models.CharField(max_length=32, unique=True, db_index=True)
    email = models.EmailField(blank=True)
    source = models.CharField(max_length=120, blank=True)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="clients",
    )
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self) -> str:
        return f"{self.name} ({self.phone_normalized})"


class DealStage(models.TextChoices):
    """Sales pipeline stages."""

    NEW = "new", "Новая заявка"
    FIRST_CONTACT = "first_contact", "Первичный контакт"
    QUALIFICATION = "qualification", "Квалификация"
    PROPOSAL = "proposal", "Предложение"
    NEGOTIATION = "negotiation", "Переговоры"
    WON = "won", "Успешно реализовано"
    LOST = "lost", "Отказ"


class DealQuerySet(models.QuerySet):
    """Visibility rules for deals."""

    def visible_to(self, user):
        if not getattr(user, "is_authenticated", False):
            return self.none()
        if getattr(user, "role", None) == RoleChoices.HEAD:
            return self.filter(is_spam=False)
        if getattr(user, "role", None) == RoleChoices.MANAGER:
            return self.filter(manager=user, is_spam=False)
        return self.none()


class Deal(models.Model):
    """Sales deal card."""

    objects = DealQuerySet.as_manager()

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="deals")
    title = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stage = models.CharField(max_length=32, choices=DealStage.choices, default=DealStage.NEW, db_index=True)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="managed_deals",
    )
    inbound_request_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    reply_draft = models.TextField(blank=True)
    reply_approved_at = models.DateTimeField(null=True, blank=True)
    reply_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_replies",
    )
    created_without_ai = models.BooleanField(default=False)
    risk_flagged = models.BooleanField(default=False)
    is_spam = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    next_contact_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["stage", "manager"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def stage_css_class(self) -> str:
        """Shared pipeline color class for templates."""

        from .pipeline import stage_css_class

        return stage_css_class(self.stage)


class DealLogAction(models.TextChoices):
    """Machine-readable deal log actions."""

    DEAL_CREATED = "deal_created", "Сделка создана"
    STAGE_CHANGED = "stage_changed", "Этап изменен"
    MANAGER_CHANGED = "manager_changed", "Ответственный изменен"
    COMMENT_ADDED = "comment_added", "Комментарий добавлен"
    REPLY_APPROVED = "reply_approved", "Ответ подтвержден"


class DealLog(models.Model):
    """Audit entry for deal changes."""

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="logs")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deal_logs",
    )
    action = models.CharField(max_length=32, choices=DealLogAction.choices, db_index=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"{self.action} for deal {self.deal_id}"

    @property
    def actor_display(self) -> str:
        """Human-readable actor for the deal history UI."""

        if self.user_id and self.user:
            return self.user.full_name or self.user.username
        return "Система"

    @property
    def change_summary(self) -> str:
        """Human-readable change text while keeping stored values machine-readable."""

        if self.action == DealLogAction.DEAL_CREATED:
            responsible_value = self.new_value or (str(self.deal.manager_id) if self.deal.manager_id else "")
            responsible = self._user_label(responsible_value) if responsible_value else "не задан"
            return f"Сделка создана · ответственный: {responsible}"
        if self.action == DealLogAction.STAGE_CHANGED:
            return f"{self._stage_label(self.old_value)} → {self._stage_label(self.new_value)}"
        if self.action == DealLogAction.MANAGER_CHANGED:
            if not self.old_value and self.new_value:
                return f"Ответственный назначен: {self._user_label(self.new_value)}"
            return f"Ответственный: {self._user_label(self.old_value)} → {self._user_label(self.new_value)}"
        if self.action == DealLogAction.COMMENT_ADDED:
            return "Добавлен комментарий"
        if self.action == DealLogAction.REPLY_APPROVED:
            return "Ответ подтвержден"
        if self.old_value or self.new_value:
            return f"{self.old_value} → {self.new_value}".strip()
        return self.get_action_display()

    @staticmethod
    def _stage_label(value: str) -> str:
        if not value:
            return "не задано"
        try:
            return DealStage(value).label
        except ValueError:
            return value

    @staticmethod
    def _user_label(value: str) -> str:
        if not value:
            return "не задан"
        try:
            user = User.objects.only("id", "full_name", "username").get(pk=int(value))
        except (TypeError, ValueError, User.DoesNotExist):
            return f"Пользователь #{value}"
        return user.full_name or user.username


class DealComment(models.Model):
    """User comment on a deal."""

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="deal_comments",
    )
    text = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"Comment by {self.author_id} on deal {self.deal_id}"
