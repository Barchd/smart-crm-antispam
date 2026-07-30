"""Phone normalization helpers for CRM and intake."""

from __future__ import annotations

import phonenumbers
from phonenumbers import PhoneNumberFormat


def normalize_phone(raw_phone: str, *, region: str = "RU") -> str:
    """Normalize a phone number to E.164."""

    value = (raw_phone or "").strip()
    if not value:
        raise ValueError("Телефон обязателен")

    parsed = phonenumbers.parse(value, region)
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("Некорректный телефон")

    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)


