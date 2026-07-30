"""AI processing service for inbound requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from crm.models import RoleChoices, User
from intake.models import InboundRequest, InboundRequestStatus, ProcessingLog
from intake.risk import decision_for_score, evaluate_rules
from intake.services import (
    clean_deal_title_candidate,
    create_crm_entities_from_request,
    hide_deal_as_spam_for_request,
    invalid_phone_log_details,
    is_technical_deal_title,
    store_risk_result,
)

from .client import AIModelUnavailable, create_ai_client
from .schemas import AIAnalysis


@dataclass(frozen=True)
class BackpressureState:
    active: bool
    reason: str
    details: dict[str, int]


def should_force_ai_fail(inbound: InboundRequest) -> bool:
    """Allow deterministic demo failures only in debug mode."""

    metadata = inbound.raw_payload_json.get("metadata") or inbound.raw_payload_json.get("extra") or {}
    return bool(settings.DEBUG and (inbound.raw_payload_json.get("force_ai_fail") is True or metadata.get("force_ai_fail") is True))


def active_manager_by_id(manager_id: int | None) -> User | None:
    if manager_id is None:
        return None
    return User.objects.filter(id=manager_id, is_active=True, role=RoleChoices.MANAGER).first()


def normalized_ai_topic(*, analysis: AIAnalysis) -> str:
    """Return a customer-meaning topic from AI fields, never a source/channel label."""

    for value in (analysis.topic, analysis.need, analysis.summary):
        candidate = clean_deal_title_candidate(value)
        if candidate and not is_technical_deal_title(candidate):
            return candidate[:120]
    return ""


def ai_risk_score(*, analysis: AIAnalysis) -> int:
    """Convert AI moderation probabilities to the common 0..100 risk scale."""

    return int(
        round(
            max(
                analysis.spam_probability,
                analysis.toxicity,
                analysis.troll_probability,
                analysis.off_topic_probability,
            )
            * 100
        )
    )


def ai_moderation_reasons(*, analysis: AIAnalysis) -> list[str]:
    """Build human-readable reasons from AI moderation scores and labels."""

    reasons: list[str] = []
    if analysis.spam_probability >= 0.6:
        reasons.append("AI: spam")
    if analysis.category == "spam":
        reasons.append("AI category: spam")
    if analysis.toxicity >= 0.6:
        reasons.append("AI: toxicity")
    if analysis.troll_probability >= 0.6:
        reasons.append("AI: troll")
    if analysis.off_topic_probability >= 0.6:
        reasons.append("AI: off_topic")
    for label in analysis.moderation_labels:
        reason = f"AI label: {label}"
        if reason not in reasons:
            reasons.append(reason)
    return reasons


def is_explicit_ai_spam(*, analysis: AIAnalysis) -> bool:
    """Return whether AI gave a definitive spam verdict, not just a risk score."""

    return (
        analysis.category == "spam"
        or "spam" in analysis.moderation_labels
        or analysis.spam_probability >= 0.9
    )


def ai_backpressure_state() -> BackpressureState:
    """Return whether AI calls should be skipped to protect the model/server."""

    if not settings.AI_BACKPRESSURE_ENABLED:
        return BackpressureState(active=False, reason="", details={})

    queue_size = InboundRequest.objects.filter(
        Q(status=InboundRequestStatus.RECEIVED) | Q(status=InboundRequestStatus.RETRY_WAIT)
    ).count()
    retry_cutoff = timezone.now() - timedelta(minutes=settings.AI_RETRY_BACKPRESSURE_WINDOW_MINUTES)
    recent_ai_retries = ProcessingLog.objects.filter(step="ai_retry_wait", created_at__gte=retry_cutoff).count()
    details = {"queue_size": queue_size, "recent_ai_retries": recent_ai_retries}

    if queue_size >= settings.AI_QUEUE_BACKPRESSURE_THRESHOLD:
        return BackpressureState(active=True, reason="ai queue backpressure", details=details)
    if recent_ai_retries >= settings.AI_RETRY_BACKPRESSURE_THRESHOLD:
        return BackpressureState(active=True, reason="ai retry backpressure", details=details)
    return BackpressureState(active=False, reason="", details=details)


def save_ai_analysis(*, inbound: InboundRequest, analysis: AIAnalysis) -> InboundRequest:
    """Persist trusted AI fields and ignore invalid employee ids."""

    inbound.ai_topic = normalized_ai_topic(analysis=analysis)
    inbound.ai_need = analysis.need
    inbound.ai_urgency = analysis.urgency
    inbound.ai_category = analysis.category
    inbound.ai_spam_probability = analysis.spam_probability
    inbound.ai_toxicity = analysis.toxicity
    inbound.ai_troll_probability = analysis.troll_probability
    inbound.ai_off_topic_probability = analysis.off_topic_probability
    inbound.ai_moderation_labels = analysis.moderation_labels
    inbound.ai_summary = analysis.summary
    inbound.ai_suggested_reply = analysis.suggested_reply
    inbound.ai_suggested_department = analysis.department
    inbound.ai_suggested_employee = active_manager_by_id(analysis.suggested_employee_id)
    inbound.save(
        update_fields=[
            "ai_topic",
            "ai_need",
            "ai_urgency",
            "ai_category",
            "ai_spam_probability",
            "ai_toxicity",
            "ai_troll_probability",
            "ai_off_topic_probability",
            "ai_moderation_labels",
            "ai_summary",
            "ai_suggested_reply",
            "ai_suggested_department",
            "ai_suggested_employee",
            "updated_at",
        ]
    )
    return inbound


def process_without_ai_due_backpressure(*, inbound: InboundRequest, decision: str, backpressure: BackpressureState) -> InboundRequest:
    """Skip model call under load and finish by deterministic rules only."""

    if decision == "suspicious":
        hide_deal_as_spam_for_request(inbound=inbound)
        inbound.status = InboundRequestStatus.SUSPICIOUS
        inbound.save(update_fields=["status", "updated_at"])
        ProcessingLog.objects.create(
            inbound_request=inbound,
            step="ai_backpressure_suspicious",
            status=inbound.status,
            message=backpressure.reason,
            details_json=backpressure.details,
        )
        return inbound

    deal = create_crm_entities_from_request(
        inbound=inbound,
        risk_flagged=decision == "risk_flagged",
        created_without_ai=True,
    )
    inbound.status = InboundRequestStatus.PROCESSED
    inbound.processed_at = timezone.now()
    inbound.linked_deal = deal
    inbound.linked_client = deal.client
    inbound.save(update_fields=["status", "processed_at", "linked_deal", "linked_client", "updated_at"])
    ProcessingLog.objects.create(
        inbound_request=inbound,
        step="ai_backpressure_fallback",
        status=inbound.status,
        message=backpressure.reason,
        details_json=backpressure.details,
    )
    return inbound


def mark_ai_retry_or_fallback(*, inbound: InboundRequest, error_message: str) -> InboundRequest:
    """Retry AI failures up to the configured limit, then create a fallback deal."""

    inbound.retry_count += 1
    inbound.last_error = error_message[:1000]
    if inbound.retry_count < settings.AI_MAX_ATTEMPTS:
        inbound.status = InboundRequestStatus.RETRY_WAIT
        inbound.next_retry_at = timezone.now() + timedelta(minutes=inbound.retry_count)
        inbound.save(update_fields=["retry_count", "last_error", "status", "next_retry_at", "updated_at"])
        ProcessingLog.objects.create(inbound_request=inbound, step="ai_retry_wait", status=inbound.status, message=inbound.last_error)
        return inbound

    deal = create_crm_entities_from_request(
        inbound=inbound,
        risk_flagged=inbound.risk_score_rules >= 30,
        created_without_ai=True,
    )
    inbound.status = InboundRequestStatus.PROCESSED
    inbound.processed_at = timezone.now()
    inbound.next_retry_at = None
    inbound.linked_deal = deal
    inbound.linked_client = deal.client
    inbound.save(update_fields=["status", "processed_at", "next_retry_at", "linked_deal", "linked_client", "updated_at"])
    ProcessingLog.objects.create(inbound_request=inbound, step="ai_fallback_created_deal", status=inbound.status, message=str(deal.id))
    return inbound


@transaction.atomic
def process_request_with_ai(*, inbound: InboundRequest, client=None) -> InboundRequest:
    """Process one inbound request through rules, AI validation and CRM creation."""

    risk = evaluate_rules(inbound)
    store_risk_result(inbound=inbound, risk=risk)

    if not risk.phone_valid:
        hide_deal_as_spam_for_request(inbound=inbound)
        inbound.status = InboundRequestStatus.BLOCKED
        inbound.last_error = "Телефон не разбирается"
        inbound.save(update_fields=["status", "last_error", "updated_at"])
        ProcessingLog.objects.create(
            inbound_request=inbound,
            step="business_validation_failed",
            status=inbound.status,
            message=f"{inbound.last_error}: {inbound.phone_raw or 'пусто'}",
            details_json=invalid_phone_log_details(inbound=inbound, error_message=inbound.last_error),
        )
        return inbound

    rules_decision = decision_for_score(inbound.risk_score_rules, blocklisted=risk.blocklisted)
    if rules_decision == "blocked":
        hide_deal_as_spam_for_request(inbound=inbound)
        inbound.status = InboundRequestStatus.BLOCKED
        inbound.save(update_fields=["status", "updated_at"])
        ProcessingLog.objects.create(inbound_request=inbound, step="rules_blocked", status=inbound.status, message=inbound.spam_reason)
        return inbound

    backpressure = ai_backpressure_state()
    if backpressure.active:
        return process_without_ai_due_backpressure(inbound=inbound, decision=rules_decision, backpressure=backpressure)

    try:
        if should_force_ai_fail(inbound):
            raise AIModelUnavailable("Forced AI failure")
        analysis = (client or create_ai_client()).analyze(inbound=inbound)
    except AIModelUnavailable as exc:
        return mark_ai_retry_or_fallback(inbound=inbound, error_message=str(exc))

    save_ai_analysis(inbound=inbound, analysis=analysis)
    final_score = max(inbound.risk_score_rules, ai_risk_score(analysis=analysis))
    inbound.risk_score_final = final_score
    ai_reasons = ai_moderation_reasons(analysis=analysis)
    if ai_reasons:
        existing_reasons = [reason.strip() for reason in (inbound.spam_reason or "").split(",") if reason.strip()]
        inbound.spam_reason = ", ".join(existing_reasons + [reason for reason in ai_reasons if reason not in existing_reasons])
    inbound.save(update_fields=["risk_score_final", "spam_reason", "updated_at"])
    ProcessingLog.objects.create(
        inbound_request=inbound,
        step="ai_analyzed",
        status=inbound.status,
        details_json={
            "final_score": final_score,
            "ai_scores": {
                "spam": analysis.spam_probability,
                "toxicity": analysis.toxicity,
                "troll": analysis.troll_probability,
                "off_topic": analysis.off_topic_probability,
            },
            "moderation_labels": analysis.moderation_labels,
        },
    )

    explicit_spam = is_explicit_ai_spam(analysis=analysis)
    final_decision = "blocked" if explicit_spam else decision_for_score(final_score, blocklisted=False)
    if final_decision == "blocked":
        hide_deal_as_spam_for_request(inbound=inbound)
        inbound.status = InboundRequestStatus.BLOCKED
        inbound.save(update_fields=["status", "updated_at"])
        ProcessingLog.objects.create(
            inbound_request=inbound,
            step="ai_blocked",
            status=inbound.status,
            message="explicit spam" if explicit_spam else str(final_score),
        )
        return inbound
    if final_decision == "suspicious":
        hide_deal_as_spam_for_request(inbound=inbound)
        inbound.status = InboundRequestStatus.SUSPICIOUS
        inbound.save(update_fields=["status", "updated_at"])
        ProcessingLog.objects.create(inbound_request=inbound, step="ai_suspicious", status=inbound.status, message=str(final_score))
        return inbound

    deal = create_crm_entities_from_request(
        inbound=inbound,
        risk_flagged=final_decision == "risk_flagged",
        created_without_ai=False,
    )
    inbound.status = InboundRequestStatus.PROCESSED
    inbound.processed_at = timezone.now()
    inbound.linked_deal = deal
    inbound.linked_client = deal.client
    inbound.save(update_fields=["status", "processed_at", "linked_deal", "linked_client", "updated_at"])
    ProcessingLog.objects.create(inbound_request=inbound, step="ai_processed", status=inbound.status, message=str(deal.id))
    return inbound
