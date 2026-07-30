"""CRM views for auth scaffolding in P1."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import ProtectedError
from django.db.models import Max, Q
from django.contrib.auth import get_user_model
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render

from ai.client import AIModelUnavailable
from ai.replies import generate_reply_draft
from channels.forms import RegenerateReplyForm, SendMessageForm
from channels.models import Dialog
from channels.services import send_dialog_message

from .access import get_visible_or_404, is_head
from .forms import ClientForm, CrmUserCreateForm, CrmUserUpdateForm, DealCommentForm, DealCreateForm, DealPermissionForm, DealStageTransitionForm
from .models import Client, Deal, DealLog, DealLogAction, DealStage
from .pipeline import build_pipeline_steps
from .services import add_deal_comment, approve_deal_reply, change_deal_manager, change_deal_stage, create_deal, update_deal_editable_fields


def root_redirect(request):
    """Send anonymous users to login and authenticated users to CRM."""

    if request.user.is_authenticated:
        return redirect("deals")
    return redirect("login")


@login_required
def deals_index(request):
    """List visible deals for the current user."""

    deals = Deal.objects.visible_to(request.user).select_related("client", "manager").annotate(last_dialog_at=Max("dialogs__last_message_at"))
    search = request.GET.get("q", "").strip()
    stage = request.GET.get("stage", "").strip()
    manager_id = request.GET.get("manager", "").strip()
    if search:
        deals = deals.filter(Q(title__icontains=search) | Q(client__name__icontains=search) | Q(client__phone_normalized__icontains=search))
    if stage:
        deals = deals.filter(stage=stage)
    if manager_id and is_head(request.user):
        deals = deals.filter(manager_id=manager_id)
    deals = deals.order_by("-last_dialog_at", "-created_at", "-id")

    return render(
        request,
        "crm/deals_index.html",
        {
            "user_full_name": getattr(request.user, "full_name", request.user.get_username()),
            "user_role": getattr(request.user, "role", ""),
            "deals": deals,
            "managers": get_user_model().objects.filter(is_active=True, role="manager"),
            "selected_stage": stage,
            "search": search,
        },
    )


@login_required
def deal_detail(request, pk: int):
    """Show one visible deal or hide it with 404."""

    deal = get_visible_or_404(
        Deal.objects.select_related("client", "manager", "reply_approved_by").prefetch_related("logs", "comments"),
        user=request.user,
        pk=pk,
    )
    if request.method == "POST":
        deal_form = DealPermissionForm(request.POST, instance=deal, user=request.user)
        if deal_form.is_valid():
            deal.refresh_from_db()
            new_manager = deal_form.cleaned_data["manager"]
            if is_head(request.user) and deal.manager_id != new_manager.id:
                change_deal_manager(deal=deal, new_manager=new_manager, user=request.user)
            update_deal_editable_fields(
                deal=deal,
                title=deal_form.cleaned_data["title"],
                amount=deal_form.cleaned_data["amount"],
                next_contact_at=deal_form.cleaned_data["next_contact_at"],
                reply_draft=deal_form.cleaned_data["reply_draft"],
            )
            messages.success(request, "Сделка обновлена")
            return redirect("deal_detail", pk=deal.pk)
    else:
        deal_form = DealPermissionForm(instance=deal, user=request.user)

    from intake.models import InboundRequest

    inbound_request = None
    if deal.inbound_request_id:
        inbound_request = InboundRequest.objects.select_related("ai_suggested_employee", "linked_client", "linked_deal").filter(pk=deal.inbound_request_id).first()
    deal_logs = DealLog.objects.filter(deal=deal).select_related("user").order_by("created_at", "id")
    terminal_from_stage = ""
    if deal.stage in {DealStage.WON, DealStage.LOST}:
        terminal_log = (
            DealLog.objects.filter(deal=deal, action=DealLogAction.STAGE_CHANGED, new_value=deal.stage)
            .order_by("-created_at", "-id")
            .first()
        )
        terminal_from_stage = terminal_log.old_value if terminal_log else ""
    pipeline_open_steps, pipeline_terminal_steps = build_pipeline_steps(
        current_stage=deal.stage,
        terminal_from_stage=terminal_from_stage,
    )
    dialogs = (
        Dialog.objects.visible_to(request.user)
        .filter(deal=deal)
        .select_related("channel")
        .prefetch_related("messages__sent_by")
        .order_by("-last_message_at", "-id")
    )
    default_dialog = dialogs.first()
    return render(
        request,
        "crm/deal_detail.html",
        {
            "deal": deal,
            "deal_form": deal_form,
            "inbound_request": inbound_request,
            "deal_logs": deal_logs,
            "pipeline_open_steps": pipeline_open_steps,
            "pipeline_terminal_steps": pipeline_terminal_steps,
            "dialogs": dialogs,
            "default_dialog": default_dialog,
            "message_form": SendMessageForm(dialogs=dialogs, initial_text=deal.reply_draft, default_dialog=default_dialog),
            "regenerate_form": RegenerateReplyForm(),
            "comment_form": DealCommentForm(),
        },
    )


@login_required
def deal_edit(request, pk: int):
    """Keep old edit URLs as redirects; editing now happens in the deal card."""

    deal = get_visible_or_404(Deal.objects.all(), user=request.user, pk=pk)
    return redirect("deal_detail", pk=deal.pk)


@login_required
def deal_stage_change(request, pk: int):
    """Move a visible deal through one allowed pipeline transition."""

    if request.method != "POST":
        raise PermissionDenied
    deal = get_visible_or_404(Deal.objects.all(), user=request.user, pk=pk)
    form = DealStageTransitionForm(request.POST, deal=deal)
    if not form.is_valid():
        error = form.errors.get("stage", ["Недопустимый переход этапа."])[0]
        return HttpResponseBadRequest(str(error))

    deal.refresh_from_db()
    try:
        change_deal_stage(deal=deal, new_stage=form.cleaned_data["stage"], user=request.user)
    except ValidationError as exc:
        return HttpResponseBadRequest(" ".join(exc.messages))
    messages.success(request, f"Этап изменён на «{deal.get_stage_display()}»")
    return redirect("deal_detail", pk=deal.pk)


@login_required
def deal_delete(request, pk: int):
    """Head-only physical deletion for erroneous MVP deals."""

    if not is_head(request.user) or request.method != "POST":
        raise PermissionDenied
    deal = get_visible_or_404(Deal.objects.all(), user=request.user, pk=pk)
    title = deal.title
    deal.delete()
    messages.success(request, f"Сделка «{title}» удалена")
    return redirect("deals")


@login_required
def deal_create(request):
    """Create a manual deal."""

    if request.method == "POST":
        form = DealCreateForm(request.POST, user=request.user)
        if form.is_valid():
            deal = create_deal(
                client=form.cleaned_data["client"],
                title=form.cleaned_data["title"],
                amount=form.cleaned_data["amount"],
                manager=form.cleaned_data["manager"],
                user=request.user,
                next_contact_at=form.cleaned_data["next_contact_at"],
                reply_draft=form.cleaned_data["reply_draft"],
            )
            messages.success(request, "Сделка создана")
            return redirect("deal_detail", pk=deal.pk)
    else:
        form = DealCreateForm(user=request.user)
    return render(request, "crm/deal_form.html", {"form": form, "title": "Создание сделки"})


@login_required
def deal_comment_add(request, pk: int):
    """Add a comment to a visible deal."""

    deal = get_visible_or_404(Deal.objects.all(), user=request.user, pk=pk)
    form = DealCommentForm(request.POST)
    if form.is_valid():
        add_deal_comment(deal=deal, author=request.user, text=form.cleaned_data["text"])
        messages.success(request, "Комментарий добавлен")
    return redirect("deal_detail", pk=deal.pk)


@login_required
def deal_reply_approve(request, pk: int):
    """Approve the current reply draft without external sending."""

    deal = get_visible_or_404(Deal.objects.all(), user=request.user, pk=pk)
    if request.method != "POST":
        raise PermissionDenied
    approve_deal_reply(deal=deal, user=request.user)
    messages.success(request, "Ответ подтвержден")
    return redirect("deal_detail", pk=deal.pk)


@login_required
def deal_message_send(request, pk: int):
    """Send an edited response to the same channel as the selected dialog."""

    deal = get_visible_or_404(Deal.objects.all(), user=request.user, pk=pk)
    if request.method != "POST":
        raise PermissionDenied
    dialogs = Dialog.objects.visible_to(request.user).filter(deal=deal).select_related("channel")
    form = SendMessageForm(request.POST, dialogs=dialogs, initial_text=deal.reply_draft)
    if not form.is_valid():
        messages.error(request, "Не удалось отправить ответ. Проверьте канал и текст.")
        return redirect("deal_detail", pk=deal.pk)
    message = send_dialog_message(
        dialog=form.cleaned_data["dialog"],
        deal=deal,
        text=form.cleaned_data["text"],
        user=request.user,
    )
    if message.status == "sent":
        messages.success(request, "Ответ отправлен в канал клиента")
    else:
        messages.error(request, "Ответ сохранен, но доставка в канал завершилась ошибкой")
    return redirect("deal_detail", pk=deal.pk)


@login_required
def deal_reply_regenerate(request, pk: int):
    """Generate a new editable reply draft from manager prompt and dialog context."""

    deal = get_visible_or_404(Deal.objects.select_related("client"), user=request.user, pk=pk)
    if request.method != "POST":
        raise PermissionDenied
    dialogs = Dialog.objects.visible_to(request.user).filter(deal=deal).select_related("channel")
    dialog = dialogs.filter(pk=request.POST.get("dialog")).first() or dialogs.order_by("-last_message_at", "-id").first()
    if dialog is None:
        messages.error(request, "Нельзя запросить новый ответ: у сделки нет канала сообщений.")
        return redirect("deal_detail", pk=deal.pk)

    form = RegenerateReplyForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Введите промпт для нового варианта ответа.")
        return redirect("deal_detail", pk=deal.pk)

    try:
        result = generate_reply_draft(deal=deal, dialog=dialog, manager_prompt=form.cleaned_data["prompt"])
    except AIModelUnavailable as exc:
        messages.error(request, f"AI не смог подготовить новый ответ: {exc}")
        return redirect("deal_detail", pk=deal.pk)

    deal.reply_draft = result.text
    deal.save(update_fields=["reply_draft", "updated_at"])
    messages.success(request, "Новый вариант ответа подготовлен. Проверьте текст перед отправкой.")
    return redirect("deal_detail", pk=deal.pk)


@login_required
def clients_index(request):
    """List visible clients."""

    clients = Client.objects.visible_to(request.user).select_related("manager")
    search = request.GET.get("q", "").strip()
    if search:
        clients = clients.filter(Q(name__icontains=search) | Q(phone_raw__icontains=search) | Q(phone_normalized__icontains=search) | Q(email__icontains=search))
    return render(request, "crm/clients_index.html", {"clients": clients, "search": search})


@login_required
def client_create(request):
    """Create a client with duplicate protection."""

    if request.method == "POST":
        form = ClientForm(request.POST, user=request.user)
        if form.is_valid():
            client = form.save()
            messages.success(request, "Клиент создан")
            return redirect("client_edit", pk=client.pk)
    else:
        form = ClientForm(user=request.user)
    return render(request, "crm/client_form.html", {"form": form, "title": "Создание клиента"})


@login_required
def client_edit(request, pk: int):
    """Edit a visible client."""

    client = get_visible_or_404(Client.objects.select_related("manager"), user=request.user, pk=pk)
    if request.method == "POST":
        form = ClientForm(request.POST, instance=client, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Клиент обновлен")
            return redirect("client_edit", pk=client.pk)
    else:
        form = ClientForm(instance=client, user=request.user)
    return render(request, "crm/client_form.html", {"form": form, "title": "Редактирование клиента"})


@login_required
def inbound_requests_index(request):
    """Show head-only Admin Ops request cards with risk and conversation context."""

    if not is_head(request.user):
        raise PermissionDenied
    from .admin_ops import request_cards

    selected_filter = request.GET.get("status", "all").strip()
    search = request.GET.get("q", "").strip()
    cards, filter_options, selected_filter = request_cards(selected_filter=selected_filter, search=search)
    return render(
        request,
        "crm/inbound_requests_index.html",
        {
            "cards": cards,
            "filter_options": filter_options,
            "selected_filter": selected_filter,
            "search": search,
        },
    )


@login_required
def inbound_request_retry(request, pk: int):
    """Return a failed request to the worker queue from CRM Admin Ops."""

    if not is_head(request.user) or request.method != "POST":
        raise PermissionDenied
    from intake.models import InboundRequest
    from intake.services import retry_inbound_request

    inbound = get_object_or_404(InboundRequest, pk=pk)
    try:
        retry_inbound_request(inbound=inbound, user=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Заявка #{inbound.pk} возвращена в очередь")
    return redirect("inbound_requests")


@login_required
def inbound_request_not_spam(request, pk: int):
    """Head action that restores a suspicious/blocked request as a real lead."""

    if not is_head(request.user) or request.method != "POST":
        raise PermissionDenied
    from intake.models import InboundRequest
    from intake.services import restore_request_from_spam

    inbound = get_object_or_404(InboundRequest, pk=pk)
    try:
        restore_request_from_spam(inbound=inbound, user=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Заявка восстановлена, blocklist-сигналы сняты")
    return redirect("inbound_requests")


@login_required
def inbound_request_spam(request, pk: int):
    """Head action that blocks a suspicious request."""

    if not is_head(request.user) or request.method != "POST":
        raise PermissionDenied
    from intake.models import InboundRequest
    from intake.services import mark_request_as_spam

    inbound = InboundRequest.objects.get(pk=pk)
    mark_request_as_spam(inbound=inbound, user=request.user)
    messages.success(request, "Заявка помечена как спам")
    return redirect("inbound_requests")


@login_required
def inbound_request_delete(request, pk: int):
    """Head-only physical deletion for an inbound request and its processing log."""

    if not is_head(request.user) or request.method != "POST":
        raise PermissionDenied
    from intake.models import InboundRequest
    from intake.services import delete_inbound_request

    inbound = get_object_or_404(InboundRequest, pk=pk)
    deleted = delete_inbound_request(inbound=inbound)
    if deleted.linked_deal_id:
        messages.success(
            request,
            f"Заявка #{deleted.request_id} удалена. Связанная сделка сохранена.",
        )
    else:
        messages.success(request, f"Заявка #{deleted.request_id} удалена.")
    return redirect("inbound_requests")


@login_required
def users_index(request):
    """List CRM users for head users."""

    if not is_head(request.user):
        raise PermissionDenied
    users = get_user_model().objects.order_by("full_name", "username")
    return render(request, "crm/users_index.html", {"users": users})


@login_required
def user_create(request):
    """Create a CRM user and assign a role."""

    if not is_head(request.user):
        raise PermissionDenied
    if request.method == "POST":
        form = CrmUserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"Пользователь {user.username} создан")
            return redirect("users")
    else:
        form = CrmUserCreateForm()
    return render(request, "crm/user_form.html", {"form": form, "title": "Создание пользователя"})


@login_required
def user_edit(request, pk: int):
    """Edit CRM user profile fields and role."""

    if not is_head(request.user):
        raise PermissionDenied
    user_model = get_user_model()
    edited_user = get_object_or_404(user_model, pk=pk)
    if request.method == "POST":
        form = CrmUserUpdateForm(request.POST, instance=edited_user)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"Пользователь {user.username} обновлен")
            return redirect("users")
    else:
        form = CrmUserUpdateForm(instance=edited_user)
    return render(request, "crm/user_form.html", {"form": form, "title": "Редактирование пользователя"})


@login_required
def user_delete(request, pk: int):
    """Delete a CRM user when it does not break audit history."""

    if not is_head(request.user):
        raise PermissionDenied
    user_model = get_user_model()
    deleted_user = get_object_or_404(user_model, pk=pk)
    if deleted_user.pk == request.user.pk:
        messages.error(request, "Нельзя удалить самого себя")
        return redirect("users")
    if request.method == "POST":
        username = deleted_user.username
        try:
            deleted_user.delete()
        except ProtectedError:
            messages.error(request, "Пользователь связан с клиентами, сделками или журналом. Отключите его через поле Активен.")
            return redirect("users")
        messages.success(request, f"Пользователь {username} удален")
        return redirect("users")
    return render(request, "crm/user_confirm_delete.html", {"deleted_user": deleted_user})
