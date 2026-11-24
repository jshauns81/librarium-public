import json

from django.core.management.base import BaseCommand, CommandError

from librarium import library_reconciliation


class Command(BaseCommand):
    help = (
        "Save one complete native library metadata reconciliation against an explicit catalogue pin"
    )

    def add_arguments(self, parser):
        parser.add_argument("--request-key", required=True)
        parser.add_argument("--catalogue-version", required=True)
        parser.add_argument("--sha256", required=True)
        parser.add_argument("--previous")

    def handle(self, *args, **options):
        try:
            saved = library_reconciliation.reconcile(
                options["request_key"],
                options["catalogue_version"],
                options["sha256"],
                previous=options["previous"],
            )
            self.stdout.write(
                json.dumps(
                    {key: value for key, value in saved.report.items() if key != "books"},
                    sort_keys=True,
                )
            )
        except library_reconciliation.ReconciliationError as error:
            raise CommandError(str(error)) from error
