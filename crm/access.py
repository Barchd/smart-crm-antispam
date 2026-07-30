"""Backend access helpers for CRM objects."""

from __future__ import annotations

from django.http import Http404
from django.core.exceptions import ObjectDoesNotExist

from .models import RoleChoices


def is_head(user) -> bool:
    """Return whether user has head permissions."""

    return bool(getattr(user, "is_authenticated", False) and getattr(user, "role", None) == RoleChoices.HEAD)


def get_visible_or_404(queryset, *, user, **lookup):
    """Fetch an object from a visibility-filtered queryset or raise 404."""

    if not getattr(user, "is_authenticated", False):
        raise Http404
    try:
        return queryset.visible_to(user).get(**lookup)
    except ObjectDoesNotExist as exc:
        raise Http404 from exc

