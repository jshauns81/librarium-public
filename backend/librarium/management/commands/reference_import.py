import json
import os
import stat
import sys
from contextlib import ExitStack
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from librarium import reference_production


class Command(BaseCommand):
    help = "Import one bounded offline source-evidence packet into private native reference state"
    stealth_options = ("stdin",)

    def add_arguments(self, parser):
        parser.add_argument("packet", help="Selected JSON packet file, or - for standard input")
        parser.add_argument("--request-key", required=True)
        parser.add_argument("--bootstrap-version", default="")
        parser.add_argument("--bootstrap-sha256", default="")

    def handle(self, *args, **options):
        try:
            with ExitStack() as stack:
                if options["packet"] == "-":
                    source = options.get("stdin") or getattr(sys.stdin, "buffer", sys.stdin)
                else:
                    path = Path(options["packet"]).absolute()
                    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
                    stack.callback(os.close, fd)
                    if any(part in {"", ".", ".."} for part in str(path).split("/")[1:]):
                        raise ValueError
                    for part in path.parts[1:-1]:
                        fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        stack.callback(os.close, fd)
                    descriptor = os.open(
                        path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd
                    )
                    source = stack.enter_context(os.fdopen(descriptor, "rb"))
                    if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                        raise ValueError
                if source is None:
                    raise ValueError("Packet input is unavailable")
                raw = source.read(reference_production.MAX_PACKET_BYTES + 1)
                if isinstance(raw, str):
                    raw = raw.encode("utf-8")
                result = reference_production.import_packet(
                    raw,
                    options["request_key"],
                    bootstrap_version=options["bootstrap_version"],
                    bootstrap_sha256=options["bootstrap_sha256"],
                )
                if result["state"] != "succeeded":
                    raise CommandError(
                        "This request records a failed import; review and use a new request key"
                    )
                self.stdout.write(json.dumps(result, sort_keys=True))
        except reference_production.ProductionError as error:
            raise CommandError(str(error)) from error
        except (OSError, ValueError, UnicodeError) as error:
            raise CommandError(
                "Use a readable regular UTF-8 JSON packet file or bounded standard input"
            ) from error
