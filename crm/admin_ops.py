"""Read models for the head-only Admin Ops request cards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db.models import Count, Max, Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from channels.models import Dialog, Message
from channels.services import external_thread_id_from_payload, normalize_channel_type
from intake.clusters import ClusterInfo, cluster_info
from intake.models import InboundRequest, InboundRequestStatus, ProcessingLog
from intake.risk import decision_for_score


REQUEST_FILTERS = (
    ("all", "Все"),
    ("suspicious", "Suspicious"),
    ("errors", "Ошибки"),
    ("processed", "Processed"),
    ("blocked", "Blocked"),
)


@dataclass(frozen=True)
class RequestMessageEntry:
    direction: str
    direction_label: str
    status: str
    status_label: str
    text: str
    created_at: datetime | None
    sent_by_label: str = ""
    external_message_id: str = ""


@dataclass(frozen=True)
class InboundRequestCard:
    item: InboundRequest
    risk_score: int
    risk_band: str
    risk_band_label: str
    risk_updated_at: datetime
    latest_risk_log: ProcessingLog | None
    dialog: Dialog | None
    messages: list[RequestMessageEntry]
    processing_logs: list[ProcessingLog]
    cluster: ClusterInfo | None = None


def request_cards(*, selected_filter: str, search: str, limit: int = 50):
    """Return filtered request cards and tab counters for Admin Ops."""

    selected_filter = selected_filter if selected_filter in dict(REQUEST_FILTERS) else "all"
    queryset = (
        InboundRequest.objects.select_related("linked_client", "linked_deal")
        .prefetch_related(
            Prefetch(
                "processing_logs",
                queryset=ProcessingLog.objects.order_by("created_at", "id"),
                to_attr="admin_processing_logs",
            )
        )
        .annotate(last_inbound_activity=Max("linked_deal__dialogs__last_inbound_at"))
    )
    if selected_filter == "suspicious":
        queryset = queryset.filter(status=InboundRequestStatus.SUSPICIOUS)
    elif selected_filter == "errors":
        queryset = queryset.filter(status__in=[InboundRequestStatus.RETRY_WAIT, InboundRequestStatus.FAILED])
    elif selected_filter == "processed":
        queryset = queryset.filter(status=InboundRequestStatus.PROCESSED)
    elif selected_filter == "blocked":
        queryset = queryset.filter(status=InboundRequestStatus.BLOCKED)

    if search:
        criteria = (
            Q(phone_raw__icontains=search)
            | Q(phone_normalized__icontains=search)
            | Q(ai_topic__icontains=search)
            | Q(ai_need__icontains=search)
            | Q(external_id__icontains=search)
        )
        request_id = search.removeprefix("#")
        if request_id.isdigit():
            criteria |= Q(pk=int(request_id))
        queryset = queryset.filter(criteria)

    items = list(queryset.order_by("-last_inbound_activity", "-updated_at", "-created_at", "-id")[:limit])
    dialogs = _dialogs_by_request_key(items)
    cards = [_build_card(item=item, dialog=dialogs.get(_request_key(item))) for item in items]
    return cards, _filter_options(), selected_filter


def _filter_options() -> list[dict[str, str | int]]:
    counts = InboundRequest.objects.aggregate(
        all=Count("id"),
        suspicious=Count("id", filter=Q(status=InboundRequestStatus.SUSPICIOUS)),
        errors=Count("id", filter=Q(status__in=[InboundRequestStatus.RETRY_WAIT, InboundRequestStatus.FAILED])),
        processed=Count("id", filter=Q(status=InboundRequestStatus.PROCESSED)),
        blocked=Count("id", filter=Q(status=InboundRequestStatus.BLOCKED)),
    )
    return [{"key": key, "label": label, "count": counts[key]} for key, label in REQUEST_FILTERS]


def _request_key(item: InboundRequest) -> tuple[str, str]:
    return normalize_channel_type(item.source_type), external_thread_id_from_payload(inbound=item)


def _dialogs_by_request_key(items: list[InboundRequest]) -> dict[tuple[str, str], Dialog]:
    if not items:
        return {}
    thread_ids = {_request_key(item)[1] for item in items}
    queryset = (
        Dialog.objects.filter(external_thread_id__in=thread_ids)
        .select_related("channel", "deal", "client")
        .prefetch_related(
            Prefetch(
                "messages",
                queryset=Message.objects.select_related("sent_by").order_by("created_at", "id"),
                to_attr="admin_messages",
            )
        )
        .order_by("-last_inbound_at", "-last_message_at", "-id")
    )
    result: dict[tuple[str, str], Dialog] = {}
    for dialog in queryset:
        result.setdefault((dialog.channel.type, dialog.external_thread_id), dialog)
    return result


def _build_card(*, item: InboundRequest, dialog: Dialog | None) -> InboundRequestCard:
    logs = list(item.admin_processing_logs)
    risk_logs = [log for log in logs if log.step in {"rules_risk_scored", "ai_analyzed"}]
    latest_risk_log = risk_logs[-1] if risk_logs else None
    risk_band = decision_for_score(
        min(item.risk_score_final, 100),
        blocklisted=item.status == InboundRequestStatus.BLOCKED,
    )
    risk_band = "normal" if risk_band == "process" else risk_band
    messages = _merged_message_entries(item=item, dialog=dialog)
    return InboundRequestCard(
        item=item,
        risk_score=min(item.risk_score_final, 100),
        risk_band=risk_band,
        risk_band_label={
            "normal": "normal",
            "risk_flagged": "risk_flagged",
            "suspicious": "suspicious",
            "blocked": "blocked",
        }[risk_band],
        risk_updated_at=latest_risk_log.created_at if latest_risk_log else item.updated_at,
        latest_risk_log=latest_risk_log,
        dialog=dialog,
        messages=messages,
        processing_logs=logs,
        cluster=cluster_info(item),
    )


def _dialog_message_entries(dialog: Dialog) -> list[RequestMessageEntry]:
    entries: list[RequestMessageEntry] = []
    for message in dialog.admin_messages:
        sent_by = message.sent_by
        sent_by_label = (sent_by.full_name or sent_by.username) if sent_by else ""
        entries.append(
            RequestMessageEntry(
                direction=message.direction,
                direction_label=message.get_direction_display(),
                status=message.status,
                status_label=message.get_status_display(),
                text=message.text,
                created_at=message.created_at,
                sent_by_label=sent_by_label,
                external_message_id=message.external_message_id,
            )
        )
    return entries


def _merged_message_entries(*, item: InboundRequest, dialog: Dialog | None) -> list[RequestMessageEntry]:
    dialog_entries = _dialog_message_entries(dialog) if dialog else []
    raw_entries = _raw_message_entries(item)
    known_ids = {entry.external_message_id for entry in dialog_entries if entry.external_message_id}
    known_fallbacks = {(entry.direction, entry.text) for entry in dialog_entries if not entry.external_message_id}
    for entry in raw_entries:
        if entry.external_message_id and entry.external_message_id in known_ids:
            continue
        if not entry.external_message_id and (entry.direction, entry.text) in known_fallbacks:
            continue
        dialog_entries.append(entry)
        if entry.external_message_id:
            known_ids.add(entry.external_message_id)
    return sorted(dialog_entries, key=lambda entry: entry.created_at or item.received_at)


def _raw_message_entries(item: InboundRequest) -> list[RequestMessageEntry]:
    payload = item.raw_payload_json or {}
    payloads = [payload]
    payloads.extend(value for value in payload.get("follow_up_messages", []) if isinstance(value, dict))
    entries: list[RequestMessageEntry] = []
    for index, message_payload in enumerate(payloads):
        text = str(message_payload.get("text") or (item.message_text if index == 0 else "")).strip()
        if not text:
            continue
        entries.append(
            RequestMessageEntry(
                direction="inbound",
                direction_label="Входящее",
                status="received",
                status_label="Получено",
                text=text,
                created_at=_payload_datetime(
                    message_payload.get("received_at"),
                    fallback=item.received_at if index == 0 else item.updated_at,
                ),
                external_message_id=str(message_payload.get("message_id") or (item.external_id if index == 0 else "")),
            )
        )
    return entries


def _payload_datetime(value, *, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = parse_datetime(str(value)) if value else None
    if parsed and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed or fallback
