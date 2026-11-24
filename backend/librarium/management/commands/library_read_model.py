import json

from django.core.management.base import BaseCommand, CommandError

from librarium import library_read_model


class Command(BaseCommand):
    help = "Refresh the Postgres read model of the Calibre library, or prove it against the library"

    def add_arguments(self, parser):
        actions = parser.add_subparsers(dest="action", required=True)
        refresh = actions.add_parser("refresh", help="Import now if Calibre changed")
        refresh.add_argument("--force", action="store_true", help="Import even if unchanged")
        refresh.add_argument(
            "--hash-seconds",
            type=float,
            default=0,
            help="Then hash unhashed recorded files for up to this long",
        )
        actions.add_parser("parity", help="Compare every book with the direct reader")

    def handle(self, *args, **options):
        try:
            if options["action"] == "refresh":
                result = library_read_model.refresh(force=options["force"])
                if options["hash_seconds"] > 0:
                    result["hashed"] = library_read_model.hash_pending(options["hash_seconds"])
                self.stdout.write(json.dumps(result, sort_keys=True))
                return
            report = library_read_model.parity()
        except library_read_model.ReadModelError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(json.dumps(report, sort_keys=True))
        if not report["parity"]:
            raise CommandError("The read model differs from the direct reader")
