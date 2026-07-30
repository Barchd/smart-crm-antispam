"""CRM domain services."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.db.models import Count, Q

from .models import Client, Deal, DealComment, DealLog, DealLogAction, DealStage, RoleChoices, User
from .pipeline import validate_stage_transition


OPEN_DEAL_STAGES = (
    DealStage.NEW,
    DealStage.FIRST_CONTACT,
    DealStage.QUALIFICATION,
    DealStage.PROPOSAL,
    DealStage.NEGOTIATION,
)


def choose_responsible_manager(*, client: Client | None = None) -> User:
    """Choose a manager using the deterministic assignment rule."""

    if client and client.manager_id and client.manager.is_active and client.manager.role == RoleChoices.MANAGER:
        return client.manager

    manager = (
        User.objects.filter(is_active=True, role=RoleChoices.MANAGER)
        .annotate(open_deals_count=Count("managed_deals", filter=Q(managed_deals__stage__in=OPEN_DEAL_STAGES)))
        .order_by("open_deals_count", "id")
        .first()
    )
    if manager is None:
        raise ValueError("Нет активного менеджера для назначения")
    return manager


def log_deal_action(
    *,
    deal: Deal,
    action: str,
    user: User | None = None,
    old_value: str = "",
    new_value: str = "",
) -> DealLog:
    """Create one normalized audit entry for a deal."""

    return DealLog.objects.create(
        deal=deal,
        user=user,
        action=action,
        old_value=old_value,
        new_value=new_value,
    )


def create_deal(
    *,
    client: Client,
    title: str,
    amount: Decimal | int | str = Decimal("0"),
    manager: User | None = None,
    user: User | None = None,
    next_contact_at=None,
    inbound_request_id: int | None = None,
    reply_draft: str = "",
    created_without_ai: bool = False,
    risk_flagged: bool = False,
) -> Deal:
    """Create a deal and always write its first log entry."""

    responsible = manager or choose_responsible_manager(client=client)
    deal = Deal.objects.create(
        client=client,
        title=title,
        amount=amount,
        manager=responsible,
        next_contact_at=next_contact_at,
        inbound_request_id=inbound_request_id,
        reply_draft=reply_draft,
        created_without_ai=created_without_ai,
        risk_flagged=risk_flagged,
    )
    log_deal_action(
        deal=deal,
        action=DealLogAction.DEAL_CREATED,
        user=user,
        new_value=str(responsible.id),
    )
    log_deal_action(
        deal=deal,
        action=DealLogAction.MANAGER_CHANGED,
        user=user,
        new_value=str(responsible.id),
    )
    return deal


def update_deal_editable_fields(*, deal: Deal, title: str, amount, next_contact_at, reply_draft: str) -> Deal:
    """Update simple deal fields that do not have dedicated audit actions."""

    update_fields = ["updated_at"]
    if deal.title != title:
        deal.title = title
        update_fields.append("title")
    if deal.amount != amount:
        deal.amount = amount
        update_fields.append("amount")
    if deal.next_contact_at != next_contact_at:
        deal.next_contact_at = next_contact_at
        update_fields.append("next_contact_at")
    if deal.reply_draft != reply_draft:
        deal.reply_draft = reply_draft
        update_fields.append("reply_draft")
    if len(update_fields) > 1:
        deal.save(update_fields=update_fields)
    return deal


@transaction.atomic
def change_deal_stage(*, deal: Deal, new_stage: str, user: User | None = None) -> Deal:
    """Change deal stage only along the configured pipeline and write an audit entry."""

    old_stage = deal.stage
    validate_stage_transition(current_stage=old_stage, new_stage=new_stage)
    deal.stage = new_stage
    deal.save(update_fields=["stage", "updated_at"])
    log_deal_action(
        deal=deal,
        action=DealLogAction.STAGE_CHANGED,
        user=user,
        old_value=old_stage,
        new_value=new_stage,
    )
    return deal


def change_deal_manager(*, deal: Deal, new_manager: User, user: User | None = None) -> Deal:
    """Change responsible manager and write an audit entry."""

    if deal.manager_id == new_manager.id:
        return deal

    old_manager_id = deal.manager_id
    deal.manager = new_manager
    deal.save(update_fields=["manager", "updated_at"])
    log_deal_action(
        deal=deal,
        action=DealLogAction.MANAGER_CHANGED,
        user=user,
        old_value=str(old_manager_id),
        new_value=str(new_manager.id),
    )
    return deal


def add_deal_comment(*, deal: Deal, author: User, text: str) -> DealComment:
    """Create a comment and mirror the event into the deal log."""

    comment = DealComment.objects.create(deal=deal, author=author, text=text)
    log_deal_action(deal=deal, action=DealLogAction.COMMENT_ADDED, user=author, new_value=str(comment.id))
    return comment


def approve_deal_reply(*, deal: Deal, user: User) -> Deal:
    """Mark the prepared reply as approved without sending it anywhere."""

    deal.reply_approved_at = timezone.now()
    deal.reply_approved_by = user
    deal.save(update_fields=["reply_approved_at", "reply_approved_by", "updated_at"])
    log_deal_action(deal=deal, action=DealLogAction.REPLY_APPROVED, user=user)
    return deal
