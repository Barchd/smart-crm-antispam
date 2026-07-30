"""CRM API endpoints with backend permissions."""

from __future__ import annotations

import hmac
from datetime import timedelta, timezone as dt_timezone

from django.conf import settings
from django.utils import timezone
from ninja import NinjaAPI, Schema

from .access import is_head
from .models import Deal
from intake.models import InboundRequest, InboundRequestStatus, ProcessingLog, TrustLevel
from intake.services import create_inbound_request
from intake.webhook_config import get_webhook_secret


api = NinjaAPI(title="CRM MVP API", version="1.0.0")


class DealOut(Schema):
    id: int
    title: str
    stage: str
    manager_id: int
    client_id: int


class LeadIn(Schema):
    external_id: str
    name: str = ""
    phone: str = ""
    text: str = ""
    source: str = ""
    received_at: str | None = None
    email: str = ""
    metadata: dict = {}
    extra: dict = {}


def admin_api_allowed(request) -> bool:
    """Allow head session or matching admin token."""

    if is_head(request.user):
        return True

    expected = settings.ADMIN_API_TOKEN or ""
    provided = request.headers.get("X-Admin-Token", "")
    return bool(expected and provided and hmac.compare_digest(provided, expected))


def signature_valid(request) -> bool:
    secret = get_webhook_secret()
    timestamp = request.headers.get("X-Timestamp", "")
    signature = request.headers.get("X-Signature", "")
    if not secret or not timestamp or not signature:
        return False
    try:
        sent_at = timezone.datetime.fromtimestamp(int(timestamp), tz=dt_timezone.utc)
    except ValueError:
        return False
    if abs(timezone.now() - sent_at) > timedelta(minutes=5):
        return False
    expected = hmac.new(secret.encode("utf-8"), request.body, "sha256").hexdigest()
    return hmac.compare_digest(signature, expected)


@api.get("/deals/{deal_id}", response={200: DealOut, 404: dict})
def deal_detail(request, deal_id: int):
    try:
        deal = Deal.objects.visible_to(request.user).get(pk=deal_id)
    except Deal.DoesNotExist:
        return 404, {"detail": "Not found"}
    return DealOut(
        id=deal.id,
        title=deal.title,
        stage=deal.stage,
        manager_id=deal.manager_id,
        client_id=deal.client_id,
    )


@api.post("/intake/lead", response={202: dict, 200: dict, 401: dict})
def intake_lead(request, payload: LeadIn):
    if not signature_valid(request):
        return 401, {"detail": "Unauthorized"}
    # Trust level is set server-side from a verified header — never from the body.
    trust_header = request.headers.get("X-Intake-Trust", "").strip().lower()
    trust_level = TrustLevel.INTERNAL if trust_header == "internal" else TrustLevel.EXTERNAL
    payload_dict = payload.dict()
    result = create_inbound_request(
        payload=payload_dict,
        request=request,
        external_id=payload.external_id,
        source_type=payload.source or "api",
        trust_level=trust_level,
    )
    return result.response_status, {"request_id": result.response_request_id, "stored_request_id": result.request.id}


@api.get("/admin/requests/recent", response={200: dict, 403: dict})
def admin_requests_recent(request):
    if not admin_api_allowed(request):
        return 403, {"detail": "Forbidden"}
    items = [
        {"id": item.id, "status": item.status, "source_type": item.source_type, "external_id": item.external_id, "created_at": item.created_at.isoformat()}
        for item in InboundRequest.objects.order_by("-created_at")[:10]
    ]
    return {"items": items}


@api.get("/admin/requests/errors", response={200: dict, 403: dict})
def admin_requests_errors(request):
    if not admin_api_allowed(request):
        return 403, {"detail": "Forbidden"}
    items = [
        {"id": item.id, "status": item.status, "last_error": item.last_error[:200]}
        for item in InboundRequest.objects.filter(status__in=[InboundRequestStatus.RETRY_WAIT, InboundRequestStatus.FAILED]).order_by("-updated_at")[:20]
    ]
    return {"items": items}


@api.post("/admin/requests/{request_id}/retry", response={200: dict, 403: dict, 404: dict})
def admin_request_retry(request, request_id: int):
    if not admin_api_allowed(request):
        return 403, {"detail": "Forbidden"}
    try:
        inbound = InboundRequest.objects.get(pk=request_id)
    except InboundRequest.DoesNotExist:
        return 404, {"detail": "Not found"}
    inbound.status = InboundRequestStatus.RECEIVED
    inbound.next_retry_at = None
    inbound.locked_at = None
    inbound.last_error = ""
    inbound.save(update_fields=["status", "next_retry_at", "locked_at", "last_error", "updated_at"])
    ProcessingLog.objects.create(inbound_request=inbound, step="retried_manually", status=inbound.status, message="Manual retry from admin API")
    return {"request_id": inbound.id, "status": inbound.status}
