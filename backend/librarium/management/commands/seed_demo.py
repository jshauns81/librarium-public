from django.core.management.base import BaseCommand

from librarium.seed import seed


class Command(BaseCommand):
    help = "Add fictional metadata fixtures without touching existing works"

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=5522)

    def handle(self, *args, **options):
        seed(options["count"])
        self.stdout.write("Synthetic collection available")
