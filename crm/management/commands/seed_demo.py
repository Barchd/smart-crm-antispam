"""Seed deterministic demo CRM data."""

from __future__ import annotations

from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand

from crm.models import Client, Deal, DealStage, RoleChoices, User
from crm.pipeline import OPEN_STAGE_ORDER
from crm.phones import normalize_phone
from crm.services import change_deal_stage, create_deal


def advance_deal_to_stage(*, deal: Deal, target_stage: str) -> None:
    """Move seed data through the same ordered transitions as the CRM UI."""

    if deal.stage == target_stage:
        return
    if target_stage == DealStage.LOST:
        change_deal_stage(deal=deal, new_stage=DealStage.LOST)
        return

    final_open_stage = DealStage.NEGOTIATION if target_stage == DealStage.WON else DealStage(target_stage)
    current_index = OPEN_STAGE_ORDER.index(DealStage(deal.stage))
    final_index = OPEN_STAGE_ORDER.index(final_open_stage)
    if current_index > final_index:
        raise RuntimeError(f"Demo deal {deal.pk} cannot move backwards from {deal.stage} to {target_stage}")

    for next_stage in OPEN_STAGE_ORDER[current_index + 1 : final_index + 1]:
        change_deal_stage(deal=deal, new_stage=next_stage)
    if target_stage == DealStage.WON:
        change_deal_stage(deal=deal, new_stage=DealStage.WON)


class Command(BaseCommand):
    help = "Create demo users, clients and deals."

    def handle(self, *args, **options):
        call_command("seed_users")
        managers = list(User.objects.filter(role=RoleChoices.MANAGER, is_active=True).order_by("id")[:2])
        if len(managers) < 2:
            raise RuntimeError("seed_users did not create two active managers")

        clients_data = [
            ("Иван Петров", "+7 999 700-00-00", "ivan.demo@example.test", "site_form", managers[0], "Интересуется кредитом."),
            ("Мария Соколова", "+7 999 700-00-01", "maria.demo@example.test", "telegram", managers[1], "Trade-in текущего авто."),
            ("Олег Смирнов", "+7 999 700-00-02", "oleg.demo@example.test", "telephony", managers[0], "Просит подобрать Jolion."),
            ("Анна Орлова", "+7 999 700-00-03", "anna.demo@example.test", "ads", managers[1], "Первичный контакт."),
        ]
        clients = []
        for name, phone, email, source, manager, comment in clients_data:
            phone_normalized = normalize_phone(phone)
            client, _ = Client.objects.update_or_create(
                phone_normalized=phone_normalized,
                defaults={
                    "name": name,
                    "phone_raw": phone,
                    "email": email,
                    "source": source,
                    "manager": manager,
                    "comment": comment,
                },
            )
            clients.append(client)

        deals_data = [
            (clients[0], "Демо: кредит Jolion", Decimal("1850000"), DealStage.NEW, managers[0]),
            (clients[1], "Демо: trade-in", Decimal("2400000"), DealStage.FIRST_CONTACT, managers[1]),
            (clients[2], "Демо: предложение", Decimal("2100000"), DealStage.PROPOSAL, managers[0]),
            (clients[3], "Демо: переговоры", Decimal("1950000"), DealStage.NEGOTIATION, managers[1]),
            (clients[0], "Демо: успешно", Decimal("1750000"), DealStage.WON, managers[0]),
            (clients[1], "Демо: отказ", Decimal("2300000"), DealStage.LOST, managers[1]),
        ]
        created = 0
        for client, title, amount, stage, manager in deals_data:
            deal = Deal.objects.filter(title=title, client=client).first()
            if deal is None:
                deal = create_deal(client=client, title=title, amount=amount, manager=manager)
                created += 1
            deal.amount = amount
            deal.manager = manager
            deal.save(update_fields=["amount", "manager", "updated_at"])
            advance_deal_to_stage(deal=deal, target_stage=stage)

        self.stdout.write(self.style.SUCCESS(f"Demo clients: {len(clients)}; new demo deals: {created}"))
