import json

from django.core.management.base import BaseCommand, CommandError

from librarium import library_reconciliation


class Command(BaseCommand):
    help = "Read a saved historical reconciliation; this command does not recheck live sources"

    def add_arguments(self, parser):
        parser.add_argument("request_key")

    def handle(self, *args, **options):
        try:
            self.stdout.write(
                json.dumps(
                    library_reconciliation.read(options["request_key"]).report, sort_keys=True
                )
            )
        except library_reconciliation.ReconciliationError as error:
            raise CommandError(str(error)) from error
