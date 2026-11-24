import json

from django.core.management.base import BaseCommand

from librarium.operational_status import REPORT_SCHEMA, collect_report


class Command(BaseCommand):
    help = "Print bounded read-only operator observations as sanitized JSON"
    requires_system_checks = []  # noqa: RUF012 - Django management command interface
    requires_migrations_checks = False

    def handle(self, *args, **options):
        try:
            report = collect_report()
            output = json.dumps(report, sort_keys=True, allow_nan=False)
        except Exception:  # noqa: BLE001 - operator output must never disclose raw failures
            output = json.dumps({"schema": REPORT_SCHEMA, "state": "unavailable"})
        self.stdout.write(output)
