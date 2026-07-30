"""Backfill missing manager ids in historical deal_created logs."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from crm.models import DealLog, DealLogAction


class Command(BaseCommand):
    help = "Fill empty deal_created.new_value from the current deal manager id."

    def handle(self, *args, **options):
        updated = 0
        queryset = (
            DealLog.objects.select_related("deal")
            .filter(action=DealLogAction.DEAL_CREATED, new_value="")
            .order_by("id")
        )
        for log in queryset:
            if not log.deal.manager_id:
                continue
            log.new_value = str(log.deal.manager_id)
            log.save(update_fields=["new_value"])
            updated += 1
        self.stdout.write(self.style.SUCCESS(f"Updated {updated} deal_created logs"))
