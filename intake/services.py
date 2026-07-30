"""Services for accepting and storing inbound requests."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from crm.auth import get_client_ip
from crm.models import Client, Deal
from crm.services import OPEN_DEAL_STAGES, choose_responsible_manager, create_deal

from .models import Blocklist, BlocklistKind, IdempotencyKey, InboundRequest, InboundRequestStatus, IntakeThrottle, IntakeThrottleScope, ProcessingLog
from .risk import RESTORED_RISK_FLOOR, RiskResult, decision_for_score, effective_risk_score, email_domain, evaluate_rules


MARKDOWN_LINK_RE = re.compile(r"^\[(?P<label>.+?)\]\([^)]*\)$")


@dataclass(frozen=True)
class IntakeResult:
    request: InboundRequest
    response_status: int
    response_request_id: int


@dataclass(frozen=True)
class DeletedInboundRequest:
    """Summary returned after manual request deletion."""

    request_id: int
    linked_deal_id: int | None


def canonical_payload(payload: dict[str, Any]) -> str:
    """Return stable JSON used for payload hashing."""

    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_payload(payload).encode("utf-8")).hexdigest()


def telegram_customer_is_blocked(user_id: int | str) -> bool:
    """Return whether Telegram intake or delivery must be silently stopped."""

    candidates: list[int | str] = [str(user_id)]
    try:
        candidates.append(int(user_id))
    except (TypeError, ValueError):
        pass

    user_filter = Q()
    for candidate in candidates:
        user_filter |= Q(raw_payload_json__user_id=candidate)
    inbound = (
        InboundRequest.objects.filter(source_type="telegram")
        .filter(user_filter)
        .select_related("linked_deal")
        .order_by("-updated_at", "-id")
        .first()
    )

    if inbound is not None:
        if inbound.status == InboundRequestStatus.BLOCKED or (inbound.linked_deal and inbound.linked_deal.is_spam):
            return True
        identifiers = [
            (BlocklistKind.PHONE, inbound.phone_normalized),
            (BlocklistKind.IP, inbound.ip_address),
            (BlocklistKind.EMAIL_DOMAIN, email_domain(inbound.email_raw)),
        ]
        if any(value and Blocklist.objects.filter(kind=kind, value=value).exists() for kind, value in identifiers):
            return True

    from channels.models import ChannelType, Dialog

    return Dialog.objects.filter(
        channel__type=ChannelType.TELEGRAM,
        external_thread_id=str(user_id),
        deal__is_spam=True,
    ).exists()


def normalize_received_at(value: str | None) -> datetime:
    now = timezone.now()
    if not value:
        return now
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone=timezone.get_current_timezone())
    if parsed > now or parsed < now - timedelta(days=1):
        return now
    return parsed


def increment_throttle(*, scope: str, key: str, window_start, limit: int) -> bool:
    counter, _ = IntakeThrottle.objects.get_or_create(
        scope=scope,
        key=key,
        window_start=window_start,
        defaults={"count": 0},
    )
    counter.count += 1
    counter.save(update_fields=["count"])
    return counter.count > limit


def throttle_blocked(*, ip_address: str | None) -> tuple[bool, str]:
    now = timezone.now()
    minute = now.replace(second=0, microsecond=0)
    hour = now.replace(minute=0, second=0, microsecond=0)
    global_blocked = increment_throttle(
        scope=IntakeThrottleScope.GLOBAL,
        key="global",
        window_start=minute,
        limit=settings.INTAKE_RATE_LIMIT_GLOBAL_PER_MINUTE,
    )
    ip_blocked = False
    if ip_address:
        ip_blocked = increment_throttle(
            scope=IntakeThrottleScope.IP,
            key=ip_address,
            window_start=hour,
            limit=settings.INTAKE_RATE_LIMIT_IP_PER_HOUR,
        )
    reasons = []
    if global_blocked:
        reasons.append("global rate limit")
    if ip_blocked:
        reasons.append("ip rate limit")
    return bool(reasons), ", ".join(reasons)


def extract_headers(request) -> dict[str, str]:
    headers = {}
    for name in ("HTTP_USER_AGENT", "HTTP_X_REQUEST_ID", "HTTP_X_TIMESTAMP", "HTTP_X_SIGNATURE"):
        value = request.META.get(name)
        if value:
            headers[name] = value
    return headers


def create_raw_inbound_request(
    *,
    external_id: str,
    source_type: str,
    source_name: str,
    name_raw: str,
    phone_raw: str,
    email_raw: str = "",
    message_text: str,
    received_at,
    raw_payload_json: dict[str, Any],
    headers_json: dict[str, Any],
    ip_address: str | None = None,
    user_agent: str = "",
    status: str = InboundRequestStatus.RECEIVED,
    spam_reason: str = "",
    log_message: str = "",
    trust_level: str = "external",
) -> InboundRequest:
    """Persist a raw InboundRequest row and initial audit log.

    Used by both HTTP intake (create_inbound_request) and Telegram intake
    (create_telegram_inbound_request). Telegram skips HMAC/throttle/honeypot —
    those are HTTP-only concerns — but every create path goes through this
    function to guarantee consistent field-setting and the 'received' audit log.
    """
    inbound = InboundRequest.objects.create(
        external_id=external_id,
        source_type=source_type,
        source_name=source_name,
        name_raw=name_raw,
        phone_raw=phone_raw,
        email_raw=email_raw,
        message_text=message_text,
        received_at=received_at,
        raw_payload_json=raw_payload_json,
        payload_hash=payload_hash(raw_payload_json),
        headers_json=headers_json,
        ip_address=ip_address,
        user_agent=user_agent,
        status=status,
        spam_reason=spam_reason,
        trust_level=trust_level,
    )
    ProcessingLog.objects.create(
        inbound_request=inbound,
        step="received",
        status=status,
        message=log_message or spam_reason,
    )
    return inbound


def create_inbound_request(
    *,
    payload: dict[str, Any],
    request,
    external_id: str,
    source_type: str,
    force_status: str | None = None,
    spam_reason: str = "",
    trust_level: str = "external",
) -> IntakeResult:
    """Create a raw inbound request with throttle and idempotency handling."""

    ip_address = get_client_ip(request)
    user_agent = request.META.get("HTTP_USER_AGENT", "")
    blocked_by_rate, rate_reason = throttle_blocked(ip_address=ip_address)
    final_status = force_status or (InboundRequestStatus.BLOCKED if blocked_by_rate else InboundRequestStatus.RECEIVED)
    final_spam_reason = spam_reason or rate_reason
    key = f"{source_type}:{external_id}"

    with transaction.atomic():
        existing_key = IdempotencyKey.objects.select_for_update().filter(key=key).first()
        if existing_key:
            duplicate = InboundRequest.objects.create(
                external_id=external_id,
                source_type=source_type,
                source_name=str(payload.get("source_name") or payload.get("source") or ""),
                name_raw=str(payload.get("name") or payload.get("name_raw") or ""),
                phone_raw=str(payload.get("phone") or payload.get("phone_raw") or ""),
                email_raw=str(payload.get("email") or payload.get("email_raw") or ""),
                message_text=str(payload.get("text") or payload.get("message_text") or ""),
                received_at=normalize_received_at(payload.get("received_at")),
                raw_payload_json=payload,
                payload_hash=payload_hash(payload),
                headers_json=extract_headers(request),
                ip_address=ip_address,
                user_agent=user_agent,
                status=InboundRequestStatus.DUPLICATE,
                duplicate_of_request=existing_key.first_request,
            )
            ProcessingLog.objects.create(inbound_request=duplicate, step="duplicate_checked", status="duplicate", message="Duplicate external id")
            return IntakeResult(request=duplicate, response_status=200, response_request_id=existing_key.first_request_id)

        inbound = create_raw_inbound_request(
            external_id=external_id,
            source_type=source_type,
            source_name=str(payload.get("source_name") or payload.get("source") or ""),
            name_raw=str(payload.get("name") or payload.get("name_raw") or ""),
            phone_raw=str(payload.get("phone") or payload.get("phone_raw") or ""),
            email_raw=str(payload.get("email") or payload.get("email_raw") or ""),
            message_text=str(payload.get("text") or payload.get("message_text") or ""),
            received_at=normalize_received_at(payload.get("received_at")),
            raw_payload_json=payload,
            headers_json=extract_headers(request),
            ip_address=ip_address,
            user_agent=user_agent,
            status=final_status,
            spam_reason=final_spam_reason,
            trust_level=trust_level,
        )
        IdempotencyKey.objects.create(key=key, first_request=inbound)
        return IntakeResult(
            request=inbound,
            response_status=202 if final_status == InboundRequestStatus.RECEIVED else 200,
            response_request_id=inbound.id,
        )


@transaction.atomic
def delete_inbound_request(*, inbound: InboundRequest) -> DeletedInboundRequest:
    """Delete an inbound request without deleting the linked deal."""

    deleted = DeletedInboundRequest(
        request_id=inbound.pk,
        linked_deal_id=inbound.linked_deal_id,
    )
    from crm.models import Deal

    Deal.objects.filter(inbound_request_id=inbound.pk).update(inbound_request_id=None)
    inbound.delete()
    return deleted


def invalid_phone_log_details(*, inbound: InboundRequest, error_message: str) -> dict[str, str]:
    """Build consistent log details for phone validation failures."""

    details = {
        "error": error_message,
        "phone_raw": inbound.phone_raw,
    }
    if inbound.email_raw:
        details["email_raw"] = inbound.email_raw
    return details


@transaction.atomic
def retry_inbound_request(*, inbound: InboundRequest, user) -> InboundRequest:
    """Return a failed request to the worker queue and audit the head action."""

    if inbound.status not in {InboundRequestStatus.RETRY_WAIT, InboundRequestStatus.FAILED}:
        raise ValueError("Повторный запуск доступен только для заявок с ошибкой")
    inbound.status = InboundRequestStatus.RECEIVED
    inbound.retry_count = 0
    inbound.next_retry_at = None
    inbound.locked_at = None
    inbound.last_error = ""
    inbound.processed_at = None
    inbound.save(
        update_fields=[
            "status",
            "retry_count",
            "next_retry_at",
            "locked_at",
            "last_error",
            "processed_at",
            "updated_at",
        ]
    )
    ProcessingLog.objects.create(
        inbound_request=inbound,
        step="retried_manually",
        status=inbound.status,
        message="Manual retry from CRM Admin Ops",
        details_json={"user_id": user.id},
    )
    return inbound


def store_risk_result(*, inbound: InboundRequest, risk: RiskResult) -> InboundRequest:
    """Persist deterministic risk scoring result on an inbound request."""

    stored_score = effective_risk_score(inbound=inbound, score=risk.score)
    inbound.phone_normalized = risk.phone_normalized
    inbound.risk_score_rules = stored_score
    inbound.risk_score_final = stored_score
    inbound.spam_reason = ", ".join(risk.reasons)
    inbound.save(update_fields=["phone_normalized", "risk_score_rules", "risk_score_final", "spam_reason", "updated_at"])
    ProcessingLog.objects.create(
        inbound_request=inbound,
        step="rules_risk_scored",
        status=inbound.status,
        message=inbound.spam_reason,
        details_json={
            "score": stored_score,
            "raw_score": risk.score,
            "reasons": risk.reasons,
            "signals": [{"code": signal.code, "score": signal.score, "reason": signal.reason} for signal in risk.signals],
        },
    )
    return inbound


def create_crm_entities_from_request(
    *,
    inbound: InboundRequest,
    risk_flagged: bool = False,
    created_without_ai: bool = False,
    force_create: bool = False,
):
    """Create or reuse CRM entities while preserving the canonical open deal.

    force_create=True is reserved for the restore path: it signals that this
    call comes from _process_request_for_restore (via skip_spam_gates=True) and
    that the request was previously restored from spam (risk_restored_at is set).
    Passing force_create=True for a request that has never been restored raises
    ValueError to prevent accidental spam-gate bypass from any other call site.
    """
    if force_create and inbound.risk_restored_at is None:
        raise ValueError(
            "force_create=True requires risk_restored_at to be set. "
            "Only restore_request_from_spam may produce a force_create call."
        )

    linked_deal = open_linked_deal_for_request(inbound=inbound)
    if linked_deal is not None:
        ProcessingLog.objects.create(
            inbound_request=inbound,
            step="client_reused",
            status=inbound.status,
            message=str(linked_deal.client_id),
        )
        return reuse_deal_for_request(
            deal=linked_deal,
            inbound=inbound,
            risk_flagged=risk_flagged,
            created_without_ai=created_without_ai,
        )

    existing_dialog = dialog_for_request(inbound=inbound)
    client = existing_dialog.client if existing_dialog else None
    if client is None:
        client = Client.objects.filter(phone_normalized=inbound.phone_normalized).first()
    if client:
        ProcessingLog.objects.create(inbound_request=inbound, step="client_reused", status=inbound.status, message=str(client.id))
    else:
        manager = choose_responsible_manager()
        client = Client.objects.create(
            name=inbound.name_raw or "Без имени",
            phone_raw=inbound.phone_raw,
            phone_normalized=inbound.phone_normalized,
            email=inbound.email_raw,
            source=inbound.source_name or inbound.source_type,
            manager=manager,
            comment=inbound.message_text,
        )
        ProcessingLog.objects.create(inbound_request=inbound, step="client_created", status=inbound.status, message=str(client.id))

    existing_deal = open_dialog_deal_for_request(inbound=inbound, client=client, existing_dialog=existing_dialog)
    if existing_deal is not None:
        return reuse_deal_for_request(
            deal=existing_deal,
            inbound=inbound,
            risk_flagged=risk_flagged,
            created_without_ai=created_without_ai,
        )

    deal = create_deal(
        client=client,
        title=deal_title_from_request(inbound),
        manager=client.manager,
        inbound_request_id=inbound.id,
        reply_draft=inbound.ai_suggested_reply,
        created_without_ai=created_without_ai,
        risk_flagged=risk_flagged,
    )
    from channels.services import bind_inbound_request_to_dialog

    bind_inbound_request_to_dialog(inbound=inbound, deal=deal)
    ProcessingLog.objects.create(inbound_request=inbound, step="deal_created", status=inbound.status, message=str(deal.id))
    return deal


def dialog_for_request(*, inbound: InboundRequest):
    """Return an existing channel dialog for the inbound request."""

    try:
        from channels.services import dialog_for_inbound_request
    except ImportError:
        return None
    return dialog_for_inbound_request(inbound=inbound)


def open_linked_deal_for_request(*, inbound: InboundRequest) -> Deal | None:
    """Return the request's own linked deal when it is still open."""

    if not inbound.linked_deal_id:
        return None
    return (
        Deal.objects.select_related("client")
        .filter(pk=inbound.linked_deal_id, stage__in=OPEN_DEAL_STAGES)
        .first()
    )


def open_dialog_deal_for_request(*, inbound: InboundRequest, client: Client, existing_dialog=None):
    """Return an existing open deal for the same channel thread when one exists."""

    if existing_dialog and existing_dialog.client_id == client.id and existing_dialog.deal.stage in OPEN_DEAL_STAGES:
        return existing_dialog.deal

    from channels.models import Dialog
    from channels.services import external_thread_id_from_payload, normalize_channel_type

    thread_id = external_thread_id_from_payload(inbound=inbound)
    channel_type = normalize_channel_type(inbound.source_type)
    dialog = (
        Dialog.objects.select_related("deal")
        .filter(
            channel__type=channel_type,
            external_thread_id=thread_id,
            client=client,
            deal__stage__in=OPEN_DEAL_STAGES,
        )
        .order_by("-last_message_at", "-deal__created_at", "-id")
        .first()
    )
    return dialog.deal if dialog else None


def reuse_deal_for_request(*, deal: Deal, inbound: InboundRequest, risk_flagged: bool, created_without_ai: bool) -> Deal:
    """Refresh and bind an existing open deal for another pass of the same thread."""

    update_reused_deal_from_request(
        deal=deal,
        inbound=inbound,
        risk_flagged=risk_flagged,
        created_without_ai=created_without_ai,
    )
    from channels.services import bind_inbound_request_to_dialog

    bind_inbound_request_to_dialog(inbound=inbound, deal=deal)
    ProcessingLog.objects.create(inbound_request=inbound, step="deal_reused", status=inbound.status, message=str(deal.id))
    return deal


def update_reused_deal_from_request(*, deal, inbound: InboundRequest, risk_flagged: bool, created_without_ai: bool) -> None:
    """Refresh draft/status fields when a new message joins an existing open deal."""

    update_fields = ["updated_at"]
    next_title = deal_title_from_request(inbound)
    has_ai_topic = bool(clean_deal_title_candidate(inbound.ai_topic)) and not is_technical_deal_title(inbound.ai_topic)
    if (has_ai_topic and deal.title != next_title) or should_replace_deal_title(current_title=deal.title, next_title=next_title):
        deal.title = next_title
        update_fields.append("title")
    if inbound.ai_suggested_reply:
        deal.reply_draft = inbound.ai_suggested_reply
        update_fields.append("reply_draft")
    if risk_flagged and not deal.risk_flagged:
        deal.risk_flagged = True
        update_fields.append("risk_flagged")
    if created_without_ai and not deal.created_without_ai:
        deal.created_without_ai = True
        update_fields.append("created_without_ai")
    if deal.is_spam:
        deal.is_spam = False
        update_fields.append("is_spam")
    deal.save(update_fields=update_fields)


def should_replace_deal_title(*, current_title: str, next_title: str) -> bool:
    """Replace technical fallback titles with a real topic or question summary."""

    current = (current_title or "").strip()
    next_value = (next_title or "").strip()
    if not next_value or is_technical_deal_title(next_value):
        return False
    if not current or is_technical_deal_title(current):
        return True
    return False


def deal_title_from_request(inbound: InboundRequest) -> str:
    """Use the best human-readable AI/customer text as deal title."""

    for value, limit in (
        (inbound.ai_topic, 255),
        (inbound.ai_need, 255),
        (inbound.ai_summary, 255),
        (inbound.message_text, 120),
    ):
        candidate = clean_deal_title_candidate(value)
        if candidate and not is_technical_deal_title(candidate):
            return candidate[:limit]
    return "Обращение клиента"


def clean_deal_title_candidate(value: str) -> str:
    """Normalize model/customer text for safe display as a deal title."""

    text = " ".join((value or "").replace("\n", " ").split())
    match = MARKDOWN_LINK_RE.match(text)
    if match:
        text = match.group("label")
    return text.replace("**", "").replace("__", "").strip(" *`_[]()")


def is_technical_deal_title(value: str) -> bool:
    """Detect fallback-like titles that should not override customer text."""

    normalized = clean_deal_title_candidate(value).casefold()
    normalized_words = " ".join(re.sub(r"[^\wа-яё]+", " ", normalized).split())
    channel_only_values = {
        "telegram",
        "telegram bot",
        "telegram lead",
        "telegram request",
        "телеграм",
        "телеграм бот",
    }
    has_channel_marker = "telegram" in normalized_words or "телеграм" in normalized_words
    has_request_marker = bool(re.search(r"\bзаявк\w*\b", normalized_words))
    return normalized_words in channel_only_values or (has_channel_marker and has_request_marker)


def process_request_by_rules(*, inbound: InboundRequest) -> InboundRequest:
    """Run non-AI business processing for one inbound request."""
    return _run_rules_processing(inbound=inbound, skip_spam_gates=False)


def _process_request_for_restore(*, inbound: InboundRequest) -> InboundRequest:
    """Run rules processing after a manual spam restore.

    Bypasses blocked/suspicious gates so the restored request can always
    create CRM entities.  Must only be called from restore_request_from_spam.
    """
    return _run_rules_processing(inbound=inbound, skip_spam_gates=True)


def _run_rules_processing(*, inbound: InboundRequest, skip_spam_gates: bool) -> InboundRequest:
    risk = evaluate_rules(inbound)
    store_risk_result(inbound=inbound, risk=risk)

    if not risk.phone_valid and not skip_spam_gates:
        hide_deal_as_spam_for_request(inbound=inbound)
        inbound.status = InboundRequestStatus.BLOCKED
        inbound.last_error = "Телефон не разбирается"
        inbound.save(update_fields=["status", "last_error", "updated_at"])
        ProcessingLog.objects.create(
            inbound_request=inbound,
            step="failed",
            status=inbound.status,
            message=f"{inbound.last_error}: {inbound.phone_raw or 'пусто'}",
            details_json=invalid_phone_log_details(inbound=inbound, error_message=inbound.last_error),
        )
        return inbound

    decision = decision_for_score(inbound.risk_score_rules, blocklisted=risk.blocklisted)
    if decision == "blocked" and not skip_spam_gates:
        hide_deal_as_spam_for_request(inbound=inbound)
        inbound.status = InboundRequestStatus.BLOCKED
        inbound.save(update_fields=["status", "updated_at"])
        ProcessingLog.objects.create(inbound_request=inbound, step="blocklist_checked", status=inbound.status, message=inbound.spam_reason)
        return inbound
    if decision == "suspicious" and not skip_spam_gates:
        hide_deal_as_spam_for_request(inbound=inbound)
        inbound.status = InboundRequestStatus.SUSPICIOUS
        inbound.save(update_fields=["status", "updated_at"])
        ProcessingLog.objects.create(inbound_request=inbound, step="marked_suspicious", status=inbound.status, message=inbound.spam_reason)
        return inbound

    deal = create_crm_entities_from_request(
        inbound=inbound,
        risk_flagged=decision == "risk_flagged",
        force_create=skip_spam_gates,
    )
    inbound.linked_client = deal.client
    inbound.linked_deal = deal
    inbound.status = InboundRequestStatus.PROCESSED
    inbound.processed_at = timezone.now()
    inbound.save(update_fields=["linked_client", "linked_deal", "status", "processed_at", "updated_at"])
    return inbound


def hide_deal_as_spam_for_request(*, inbound: InboundRequest) -> Deal | None:
    """Hide an already-created deal when its request becomes spam-like."""

    deal = None
    if inbound.linked_deal_id:
        deal = Deal.objects.filter(pk=inbound.linked_deal_id).first()
    if deal is None:
        dialog = dialog_for_request(inbound=inbound)
        deal = dialog.deal if dialog else None
    if deal is None or deal.is_spam:
        return deal
    deal.is_spam = True
    deal.save(update_fields=["is_spam", "updated_at"])
    ProcessingLog.objects.create(
        inbound_request=inbound,
        step="deal_hidden_as_spam",
        status=inbound.status,
        message=str(deal.id),
    )
    return deal


@transaction.atomic
def restore_request_from_spam(*, inbound: InboundRequest, user) -> InboundRequest:
    """Restore a suspicious/blocked request and remove matching blocklist entries."""

    if inbound.status not in {InboundRequestStatus.SUSPICIOUS, InboundRequestStatus.BLOCKED}:
        raise ValueError("Восстановить можно только подозрительную или заблокированную заявку")

    identifiers = (
        (BlocklistKind.PHONE, inbound.phone_normalized),
        (BlocklistKind.IP, inbound.ip_address),
        (BlocklistKind.EMAIL_DOMAIN, email_domain(inbound.email_raw)),
    )
    removed_entries = 0
    for kind, value in identifiers:
        if value:
            removed, _ = Blocklist.objects.filter(kind=kind, value=value).delete()
            removed_entries += removed

    inbound.status = InboundRequestStatus.RECEIVED
    inbound.last_error = ""
    inbound.next_retry_at = None
    inbound.risk_restored_at = timezone.now()
    inbound.ai_spam_probability = None
    inbound.ai_toxicity = None
    inbound.ai_troll_probability = None
    inbound.ai_off_topic_probability = None
    inbound.ai_moderation_labels = []
    if inbound.ai_category == "spam":
        inbound.ai_category = ""
    inbound.save(
        update_fields=[
            "status",
            "last_error",
            "next_retry_at",
            "risk_restored_at",
            "ai_spam_probability",
            "ai_toxicity",
            "ai_troll_probability",
            "ai_off_topic_probability",
            "ai_moderation_labels",
            "ai_category",
            "updated_at",
        ]
    )
    ProcessingLog.objects.create(
        inbound_request=inbound,
        step="restored_from_spam",
        status=inbound.status,
        message="Manual restore from CRM Admin Ops",
        details_json={
            "user_id": user.id,
            "removed_blocklist_entries": removed_entries,
            "risk_floor": RESTORED_RISK_FLOOR,
        },
    )
    return _process_request_for_restore(inbound=inbound)


def mark_request_as_spam(*, inbound: InboundRequest, user) -> InboundRequest:
    """Mark request as spam and add obvious identifiers to blocklist."""

    if inbound.phone_normalized:
        Blocklist.objects.get_or_create(kind=BlocklistKind.PHONE, value=inbound.phone_normalized, defaults={"added_by": user, "reason": "manual spam"})
    if inbound.ip_address:
        Blocklist.objects.get_or_create(kind=BlocklistKind.IP, value=inbound.ip_address, defaults={"added_by": user, "reason": "manual spam"})
    domain = email_domain(inbound.email_raw)
    if domain:
        Blocklist.objects.get_or_create(kind=BlocklistKind.EMAIL_DOMAIN, value=domain, defaults={"added_by": user, "reason": "manual spam"})
    hide_deal_as_spam_for_request(inbound=inbound)
    inbound.status = InboundRequestStatus.BLOCKED
    inbound.spam_reason = (inbound.spam_reason + ", manual spam").strip(", ")
    inbound.save(update_fields=["status", "spam_reason", "updated_at"])
    ProcessingLog.objects.create(inbound_request=inbound, step="failed", status=inbound.status, message="Manual spam")
    return inbound
