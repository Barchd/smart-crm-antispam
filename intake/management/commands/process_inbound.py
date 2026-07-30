"""Management command for the inbound processing worker."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from intake.worker import process_next_request, run_worker_loop


class Command(BaseCommand):
    help = "Process inbound requests."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process at most one request and exit.")
        parser.add_argument("--interval", type=float, default=2.0, help="Polling interval for loop mode.")

    def handle(self, *args, **options):
        if options["once"]:
            result = process_next_request()
            self.stdout.write(f"request_id={result.request_id} status={result.status} processed={result.processed}")
            return
        run_worker_loop(interval=options["interval"])

