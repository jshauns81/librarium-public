import logging
import time

from django.core.management.base import BaseCommand
from django.db import DatabaseError, close_old_connections

from librarium import (
    catalogue_status,
    catalogue_sync,
    cover_reviews,
    cover_sources,
    library_read_model,
)
from librarium.services import advance, claim

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run an independent, lease-fenced metadata inspection worker"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--step-seconds", type=float, default=0.5)

    def handle(self, *args, **options):
        try:
            return self.run_worker(**options)
        finally:
            cover_reviews.shutdown_observations()

    def run_worker(self, **options):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
        delay = max(0, min(options["step_seconds"], 2))
        while True:
            close_old_connections()
            try:
                catalogue_status.tick()
                item = claim()
                if item is None:
                    # Idle time keeps the library read model in step with Calibre.
                    library_read_model.tick()
                    cover_reviews.tick()
                    cover_sources.tick()
                    catalogue_sync.tick()
                if item:
                    assert item.lease_token is not None
                    # The pause only paces the synthetic demo; real reviews run straight through.
                    pause = delay if item.kind == "synthetic" else 0
                    steps = (
                        range(1)
                        if item.kind
                        in {
                            "epub",
                            "epub_validation",
                            "library_reconcile",
                            "book_assessment",
                        }
                        else range(item.checkpoint, 4)
                    )
                    for _ in steps:
                        if pause:
                            time.sleep(pause)
                        if not advance(item.pk, item.lease_token):
                            break
            except DatabaseError:
                if options["once"]:
                    raise
                logger.exception("worker_database_interrupted; retrying after one second")
                close_old_connections()
                time.sleep(1)
                continue
            if options["once"]:
                return
            if item is None:
                time.sleep(0.5)
