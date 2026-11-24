"""Start only the explicitly configured, separately owned synthetic Calibre writer."""

import json
import os
import re
import stat
import sys
import tarfile
from hashlib import file_digest
from pathlib import Path


def verify_runtime(archive, root, pin):
    with Path(archive).open("rb") as stream:
        if file_digest(stream, "sha256").hexdigest() != pin:
            raise RuntimeError("runtime_archive_changed")
    expected_paths = set()
    with tarfile.open(archive, "r:xz") as distribution:
        for member in distribution:
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts or member.islnk():
                raise RuntimeError("runtime_installation_changed")
            expected_paths.add(relative)
            expected_paths.update(p for p in relative.parents if p != Path("."))
            path = root / member.name
            if member.isfile():
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise RuntimeError("runtime_installation_changed")
                with (
                    distribution.extractfile(member) as expected,
                    path.open("rb") as actual,
                ):
                    if (
                        file_digest(expected, "sha256").digest()
                        != file_digest(actual, "sha256").digest()
                    ):
                        raise RuntimeError("runtime_installation_changed")
            elif member.issym() and (not path.is_symlink() or os.readlink(path) != member.linkname):
                raise RuntimeError("runtime_installation_changed")

    actual_paths = {path.relative_to(root) for path in root.rglob("*")}
    if actual_paths != expected_paths:
        raise RuntimeError("runtime_installation_changed")


EXPLANATIONS = {
    "writer_state_unavailable": "LIBRARIUM_WRITER_STATE_DIR and its config directory must be "
    "existing private directories that the writer user owns and can write.",
}


def refused(code):
    """One plain line naming a structured refusal; it never includes configured values."""
    explanation = EXPLANATIONS.get(code)
    return f"Writer refused to start: {code}." + (f" {explanation}" if explanation else "")


def main():
    project = Path(__file__).resolve().parents[1]
    if os.environ.get("LIBRARIUM_DELIVERY_ENABLED") != "1":
        raise RuntimeError("writer_disabled")
    sys.path.insert(0, str(project / "backend"))
    from librarium.delivery_writer import WriterError, writer_state

    # Calibre writes its configuration as it starts, so check the state folder first.
    try:
        writer_state(os.environ)
    except WriterError as error:
        raise RuntimeError(error.code) from None
    if "--runtime" in sys.argv:
        runtime = Path(sys.argv[sys.argv.index("--runtime") + 1]).resolve()
        pin = json.loads((project / "scripts/calibre_delivery_runtime.json").read_text())
        verify_runtime(os.environ["LIBRARIUM_WRITER_ARCHIVE"], runtime, pin["sha256"])
        binary = str(runtime / "calibre-debug")
        os.execv(binary, [binary, "-e", str(Path(__file__).resolve())])
    from librarium.delivery_broker import Broker
    from librarium.delivery_content_server import ContentServer
    from librarium.delivery_recovery import RecoveryGate
    from librarium.delivery_writer import (
        SyntheticLibraryLock,
        WriterService,
        configuration,
        read_secret,
        serve,
    )

    try:
        configured = configuration(os.environ)
    except WriterError as error:
        raise RuntimeError(error.code) from None
    pin = json.loads((project / "scripts/calibre_delivery_runtime.json").read_text())
    if configured["LIBRARIUM_WRITER_RUNTIME_SHA256"] != pin["sha256"]:
        raise RuntimeError("runtime_pin_changed")
    runtime = Path(sys.executable).parents[1]
    verify_runtime(configured["LIBRARIUM_WRITER_ARCHIVE"], runtime, pin["sha256"])
    exclusion = SyntheticLibraryLock(
        configured["LIBRARIUM_WRITER_LIBRARY_ROOT"],
        configured["LIBRARIUM_WRITER_LIBRARY_UUID"],
    )
    exclusion.__enter__()
    broker = None
    try:
        owner = ContentServer.configured(os.environ, configured["LIBRARIUM_WRITER_LIBRARY_UUID"])
        owner.exclusion = exclusion
        broker = Broker(configured["LIBRARIUM_WRITER_STATE_DIR"], owner)
        service = WriterService(
            broker,
            configured["LIBRARIUM_ARTIFACT_DIR"],
            read_secret(configured["LIBRARIUM_DELIVERY_SIGNING_KEY_FILE"]),
            pin["sha256"],
            recovery=RecoveryGate(os.environ.get("LIBRARIUM_DELIVERY_RECOVERY_DIR")),
        )
        serve(service, read_secret(configured["LIBRARIUM_WRITER_TOKEN_FILE"]))
    finally:
        if broker:
            broker.close()
        exclusion.__exit__(None, None, None)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        if not re.fullmatch(r"[a-z_]{1,64}", str(error)):
            raise
        sys.exit(refused(str(error)))
