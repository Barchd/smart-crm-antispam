"""Worker services for processing inbound requests outside HTTP requests."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ai.services import process_request_with_ai

from .alerts import notify_critical_processing_event
from .models import InboundRequest, InboundRequestStatus, ProcessingLog


class TemporaryProcessingError(RuntimeError):
    """Raised for deterministic or real non-AI temporary processing errors."""


@dataclass(frozen=True)
class WorkerResult:
    request_id: int | None
    status: str
    processed: bool


def eligible_requests(now=None):
    """Return requests that can be picked by the worker."""

    now = now or timezone.now()
    return InboundRequest.objects.filter(
        Q(status=InboundRequestStatus.RECEIVED)
        | Q(status=InboundRequestStatus.RETRY_WAIT, next_retry_at__isnull=True)
        | Q(status=InboundRequestStatus.RETRY_WAIT, next_retry_at__lte=now)
    )


def reset_stale_processing(now=None) -> int:
    """Move stale processing requests back to retry_wait so they are not lost."""

    now = now or timezone.now()
    cutoff = now - timedelta(minutes=settings.WORKER_LOCK_TIMEOUT_MINUTES)
    stale_ids = list(
        InboundRequest.objects.filter(status=InboundRequestStatus.PROCESSING, locked_at__lt=cutoff).values_list("id", flat=True)
    )
    for request_id in stale_ids:
        inbound = InboundRequest.objects.get(id=request_id)
        inbound.status = InboundRequestStatus.RETRY_WAIT
        inbound.locked_at = None
        inbound.next_retry_at = now
        inbound.save(update_fields=["status", "locked_at", "next_retry_at", "updated_at"])
        ProcessingLog.objects.create(inbound_request=inbound, step="stale_lock_released", status=inbound.status)
    return len(stale_ids)


def acquire_next_request(now=None) -> InboundRequest | None:
    """Atomically mark the oldest eligible request as processing."""

    now = now or timezone.now()
    with transaction.atomic():
        request_id = eligible_requests(now).order_by("created_at", "id").values_list("id", flat=True).first()
        if request_id is None:
            return None
        updated = eligible_requests(now).filter(id=request_id).update(
            status=InboundRequestStatus.PROCESSING,
            locked_at=now,
            updated_at=now,
        )
        if updated != 1:
            return None
    inbound = InboundRequest.objects.get(id=request_id)
    ProcessingLog.objects.create(inbound_request=inbound, step="processing_started", status=inbound.status)
    return inbound


def should_force_processing_error(inbound: InboundRequest) -> bool:
    """Support deterministic non-AI worker failures only in debug mode."""

    metadata = inbound.raw_payload_json.get("metadata") or inbound.raw_payload_json.get("extra") or {}
    force_error = inbound.raw_payload_json.get("force_error") is True or metadata.get("force_error") is True
    if not settings.DEBUG or not force_error:
        return False
    max_failures = int(inbound.raw_payload_json.get("force_error_attempts") or metadata.get("force_error_attempts") or settings.PROCESSING_MAX_ATTEMPTS)
    return inbound.retry_count < max_failures


def mark_processing_error(*, inbound: InboundRequest, exc: Exception) -> WorkerResult:
    """Apply retry/backoff for non-AI processing errors."""

    inbound.retry_count += 1
    inbound.last_error = str(exc)[:1000]
    inbound.locked_at = None
    if inbound.retry_count >= settings.PROCESSING_MAX_ATTEMPTS:
        inbound.status = InboundRequestStatus.FAILED
        inbound.next_retry_at = None
        inbound.save(update_fields=["retry_count", "last_error", "locked_at", "status", "next_retry_at", "updated_at"])
        ProcessingLog.objects.create(inbound_request=inbound, step="failed", status=inbound.status, message=inbound.last_error)
        notify_critical_processing_event(inbound=inbound, event="failed", message=inbound.last_error)
        return WorkerResult(request_id=inbound.id, status=inbound.status, processed=True)

    inbound.status = InboundRequestStatus.RETRY_WAIT
    inbound.next_retry_at = timezone.now() + timedelta(minutes=inbound.retry_count)
    inbound.save(update_fields=["retry_count", "last_error", "locked_at", "status", "next_retry_at", "updated_at"])
    ProcessingLog.objects.create(inbound_request=inbound, step="processing_retry_wait", status=inbound.status, message=inbound.last_error)
    notify_critical_processing_event(inbound=inbound, event="retry_wait", message=inbound.last_error)
    return WorkerResult(request_id=inbound.id, status=inbound.status, processed=True)


def process_acquired_request(*, inbound: InboundRequest, ai_client=None) -> WorkerResult:
    """Run full request processing for an already acquired request."""

    try:
        if should_force_processing_error(inbound):
            raise TemporaryProcessingError("Forced processing error")
        processed = process_request_with_ai(inbound=inbound, client=ai_client)
    except Exception as exc:
        return mark_processing_error(inbound=inbound, exc=exc)

    processed.locked_at = None
    processed.save(update_fields=["locked_at", "updated_at"])
    fresh = InboundRequest.objects.get(pk=processed.pk)
    fresh_payload = dict(fresh.raw_payload_json or {})
    if fresh_payload.pop("reprocess_after_current", False):
        fresh.raw_payload_json = fresh_payload
        fresh.status = InboundRequestStatus.RECEIVED
        fresh.locked_at = None
        fresh.next_retry_at = None
        fresh.save(update_fields=["raw_payload_json", "status", "locked_at", "next_retry_at", "updated_at"])
        ProcessingLog.objects.create(
            inbound_request=fresh,
            step="telegram_followup_requeued",
            status=fresh.status,
        )
        return WorkerResult(request_id=fresh.id, status=fresh.status, processed=True)
    if processed.status in {InboundRequestStatus.RETRY_WAIT, InboundRequestStatus.FAILED}:
        notify_critical_processing_event(inbound=processed, event=processed.status, message=processed.last_error)
    return WorkerResult(request_id=processed.id, status=processed.status, processed=True)


def process_next_request(*, ai_client=None) -> WorkerResult:
    """Acquire and process one eligible request."""

    reset_stale_processing()
    inbound = acquire_next_request()
    if inbound is None:
        return WorkerResult(request_id=None, status="idle", processed=False)
    return process_acquired_request(inbound=inbound, ai_client=ai_client)


def run_worker_loop(*, interval: float = 2.0) -> None:
    """Run the polling worker forever."""

    while True:
        result = process_next_request()
        if not result.processed:
            time.sleep(interval)
