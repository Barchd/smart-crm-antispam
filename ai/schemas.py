"""Validation schema for untrusted AI responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


URGENCY_CHOICES = {"low", "medium", "high"}
CATEGORY_CHOICES = {"purchase", "credit", "trade_in", "service", "complaint", "spam", "other"}
DEPARTMENT_CHOICES = {"sales", "finance", "trade_in", "service", "support", "unknown"}
FORBIDDEN_OUTPUT_KEYS = {"status", "role", "permissions", "system_prompt", "manager_id"}
MODERATION_LABEL_CHOICES = {
    "spam",
    "toxicity",
    "profanity",
    "threat",
    "troll",
    "off_topic",
    "abuse_staff",
    "scam_keywords",
    "pii_harvest",
    "job_spam",
    "prompt_injection",
    "gibberish",
    "aggression",
    "test_message",
    "wrong_company",
}
MAX_SUMMARY_LENGTH = 600
MAX_REPLY_LENGTH = 1200


class AIResponseInvalid(ValueError):
    """Raised when model output cannot be trusted."""


@dataclass(frozen=True)
class AIAnalysis:
    topic: str
    need: str
    urgency: str
    category: str
    spam_probability: float
    toxicity: float
    troll_probability: float
    off_topic_probability: float
    moderation_labels: list[str]
    department: str
    suggested_employee_id: int | None
    summary: str
    suggested_reply: str


RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "topic",
        "need",
        "urgency",
        "category",
        "spam_probability",
        "toxicity",
        "troll_probability",
        "off_topic_probability",
        "moderation_labels",
        "department",
        "ai_suggested_employee_id",
        "summary",
        "suggested_reply",
    ],
    "properties": {
        "topic": {"type": "string", "maxLength": 120},
        "need": {"type": "string", "maxLength": 600},
        "urgency": {"type": "string", "enum": sorted(URGENCY_CHOICES)},
        "category": {"type": "string", "enum": sorted(CATEGORY_CHOICES)},
        "spam_probability": {"type": "number", "minimum": 0, "maximum": 1},
        "toxicity": {"type": "number", "minimum": 0, "maximum": 1},
        "troll_probability": {"type": "number", "minimum": 0, "maximum": 1},
        "off_topic_probability": {"type": "number", "minimum": 0, "maximum": 1},
        "moderation_labels": {
            "type": "array",
            "items": {"type": "string", "enum": sorted(MODERATION_LABEL_CHOICES)},
            "maxItems": 8,
        },
        "department": {"type": "string", "enum": sorted(DEPARTMENT_CHOICES)},
        "ai_suggested_employee_id": {"type": ["integer", "null"]},
        "summary": {"type": "string", "minLength": 1, "maxLength": MAX_SUMMARY_LENGTH},
        "suggested_reply": {"type": "string", "minLength": 1, "maxLength": MAX_REPLY_LENGTH},
    },
}


def _contains_forbidden_keys(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).casefold() in FORBIDDEN_OUTPUT_KEYS:
                return True
            if _contains_forbidden_keys(nested):
                return True
    if isinstance(value, list):
        return any(_contains_forbidden_keys(item) for item in value)
    return False


def _clean_text(value: Any, *, max_length: int) -> str:
    text = str(value or "").strip()
    return text[:max_length]


def _clean_probability(value: Any, *, field: str) -> float:
    try:
        probability = float(value)
    except (TypeError, ValueError) as exc:
        raise AIResponseInvalid(f"AI response contains invalid {field}") from exc
    return min(1.0, max(0.0, probability))


def _clean_moderation_labels(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise AIResponseInvalid("AI response contains invalid moderation_labels")
    labels: list[str] = []
    for item in value[:8]:
        label = str(item or "").strip().casefold()
        if label in MODERATION_LABEL_CHOICES and label not in labels:
            labels.append(label)
    return labels


def validate_ai_payload(payload: dict[str, Any]) -> AIAnalysis:
    """Convert raw model JSON into a trusted DTO or raise."""

    if not isinstance(payload, dict) or _contains_forbidden_keys(payload):
        raise AIResponseInvalid("AI response contains forbidden control fields")

    urgency = str(payload.get("urgency", "")).strip().casefold()
    if urgency not in URGENCY_CHOICES:
        raise AIResponseInvalid("AI response contains unsupported urgency")

    category = str(payload.get("category", "")).strip().casefold()
    if category not in CATEGORY_CHOICES:
        raise AIResponseInvalid("AI response contains unsupported category")

    department = str(payload.get("department", "")).strip().casefold() or "unknown"
    if department not in DEPARTMENT_CHOICES:
        department = "unknown"

    spam_probability = _clean_probability(payload.get("spam_probability", 0), field="spam_probability")
    toxicity = _clean_probability(payload.get("toxicity", 0), field="toxicity")
    troll_probability = _clean_probability(payload.get("troll_probability", 0), field="troll_probability")
    off_topic_probability = _clean_probability(payload.get("off_topic_probability", 0), field="off_topic_probability")
    moderation_labels = _clean_moderation_labels(payload.get("moderation_labels", []))

    employee_value = payload.get("ai_suggested_employee_id")
    suggested_employee_id = None
    if employee_value not in (None, ""):
        try:
            suggested_employee_id = int(employee_value)
        except (TypeError, ValueError):
            suggested_employee_id = None

    summary = _clean_text(payload.get("summary"), max_length=MAX_SUMMARY_LENGTH)
    suggested_reply = _clean_text(payload.get("suggested_reply"), max_length=MAX_REPLY_LENGTH)
    if not summary or not suggested_reply:
        raise AIResponseInvalid("AI response contains empty summary or suggested_reply")

    return AIAnalysis(
        topic=_clean_text(payload.get("topic"), max_length=120),
        need=_clean_text(payload.get("need"), max_length=600),
        urgency=urgency,
        category=category,
        spam_probability=spam_probability,
        toxicity=toxicity,
        troll_probability=troll_probability,
        off_topic_probability=off_topic_probability,
        moderation_labels=moderation_labels,
        department=department,
        suggested_employee_id=suggested_employee_id,
        summary=summary,
        suggested_reply=suggested_reply,
    )
