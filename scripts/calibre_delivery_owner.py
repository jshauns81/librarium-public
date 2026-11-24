"""Gate 0 experiment only: one ephemeral owner, no application writer entry point."""

import base64
import json
import subprocess
import sys
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic
from unittest.mock import patch
from zipfile import ZIP_STORED, ZipFile

from calibre.constants import numeric_version
from calibre.db.legacy import LibraryDatabase


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(data):
    return sha256(data).hexdigest()


def unchanged(cache, book_id):
    return {
        "fields": {
            name: (
                tuple(sorted(cache.field_for(name, book_id)))
                if name == "formats"
                else cache.field_for(name, book_id)
            )
            for name in cache.fields
            if name not in {"last_modified", "size"}
        },
        "cover": cache.cover(book_id),
        "other": cache.format(book_id, "TXT"),
    }


def conditional(cache, target, expected, output, boundary=lambda name: None):
    """Compose public native reads and replacement under the cache's own lock."""
    with cache.write_lock:
        boundary("locked")
        if cache.library_id != target[0]:
            raise ValueError("library_uuid_changed")
        if not cache.has_id(target[1]):
            raise ValueError(
                (
                    "book_missing",
                    target[1],
                    tuple(cache.all_book_ids()),
                    cache._has_id(target[1]),
                )
            )
        if cache.field_for("uuid", target[1]) != target[2]:
            raise ValueError("book_uuid_changed")
        original = cache.format(target[1], "EPUB")
        if original is None or digest(original) != expected:
            raise ValueError("source_changed")
        before = unchanged(cache, target[1])
        boundary("fence")
        require(
            cache.add_format(target[1], "EPUB", BytesIO(output), replace=True, run_hooks=False),
            "native_gate_assertion",
        )
        boundary("replaced")
        after = cache.format(target[1], "EPUB")
        require(after == output, "native_readback_mismatch")
        after_fields = unchanged(cache, target[1])
        require(
            after_fields == before,
            (
                "unrequested_change",
                {
                    k: (before["fields"].get(k), v)
                    for k, v in after_fields["fields"].items()
                    if before["fields"].get(k) != v
                },
                [k for k in ("cover", "other") if before[k] != after_fields[k]],
            ),
        )
        require(cache.library_id == target[0], "native_gate_assertion")
        require(cache.field_for("uuid", target[1]) == target[2], "native_gate_assertion")
        receipt = {"before": expected, "after": digest(after), "size": len(after)}
        boundary("receipt")
        return receipt


# An opaque 16x16 RGB PNG, embedded so Calibre never renders a page for a cover.
COVER = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAFklEQVR42mPQiOohCTGMahjVMHw1AAAnQw4QbT/6aQAAAABJRU5ErkJggg=="
)


def epub(label):
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as z:
        z.writestr("mimetype", b"application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="book.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
        )
        z.writestr(
            "book.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
            'version="2.0" unique-identifier="uid"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:identifier id="uid">urn:uuid:00000000-0000-4000-8000-000000000001</dc:identifier>'
            f"<dc:title>{label}</dc:title><dc:creator>Example Author</dc:creator>"
            '<dc:language>en</dc:language><meta name="cover" content="cover-image"/>'
            '</metadata><manifest><item id="body" '
            'href="body.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="cover-image" href="cover.png" media-type="image/png"/></manifest>'
            '<spine><itemref idref="body"/></spine></package>',
        )
        z.writestr(
            "body.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Fixture</title></head>'
            f"<body><h1>{label}</h1><p>Synthetic text only.</p></body></html>",
        )
        z.writestr("cover.png", COVER)
    return output.getvalue()


def prove():
    require(numeric_version == (9, 17, 0), "wrong_native_runtime")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from librarium.delivery_native import NativeOwner

    started = monotonic()
    with TemporaryDirectory(prefix="librarium-delivery-gate-") as temporary:
        root = Path(temporary)
        library = root / "library"
        source = root / "original.epub"
        original, output, external = (epub(s) for s in ("Original", "Corrected", "External"))
        source.write_bytes(original)
        other = root / "other.txt"
        other.write_bytes(b"Synthetic other-format bytes\n")
        cover = root / "cover.png"
        cover.write_bytes(COVER)
        cli = Path(sys.executable).parents[1] / "calibredb"

        def oracle(*args):
            p = subprocess.run(
                [str(cli), "--with-library", str(library), *args],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            require(p.returncode == 0, p.stdout + p.stderr)
            return p.stdout

        added = oracle("add", str(source))
        # A separate call reports a cover failure instead of a silent absence.
        oracle("set_metadata", "1", "--field", f"cover:{cover}")
        oracle("add_format", "1", str(other))
        oracle("set_metadata", "1", "--field", "tags:synthetic")
        oracle("add_custom_column", "fixture", "Fixture", "text")
        oracle("set_custom", "fixture", "1", "preserved")
        database = LibraryDatabase(str(library))
        cache = database.new_api
        NativeOwner(cache, cache.library_id)
        require(not cache.maintain_page_counts.is_alive(), "native_maintenance_running")
        require(cache.cover(1) is not None, "fixture_cover_missing")
        require(cache.format(1, "TXT") == other.read_bytes(), "fixture_other_format_missing")
        require(
            cache.field_for("#fixture", 1) == "preserved",
            "fixture_custom_metadata_missing",
        )
        require(1 in cache.all_book_ids(), (added, tuple(cache.all_book_ids())))
        target = (cache.library_id, 1, cache.field_for("uuid", 1))
        try:
            with (
                patch(
                    "calibre.db.cache.run_import_plugins",
                    side_effect=AssertionError("import_hook"),
                ) as imports,
                patch(
                    "calibre.db.cache.run_plugins_on_postimport",
                    side_effect=AssertionError("postimport_hook"),
                ) as postimports,
            ):
                for changed_target in (
                    ("00000000-0000-4000-8000-000000000000", 1, target[2]),
                    (target[0], 999, target[2]),
                    (target[0], 1, "00000000-0000-4000-8000-000000000000"),
                ):
                    try:
                        conditional(cache, changed_target, digest(original), output)
                    except ValueError:
                        pass
                    else:
                        raise AssertionError("identity_fence_did_not_refuse")
                    require(cache.format(1, "EPUB") == original, "native_gate_assertion")

                events = []
                attempted, completed = Event(), Event()
                failures = []

                def competitor():
                    attempted.set()
                    try:
                        cache.add_format(1, "EPUB", BytesIO(external), run_hooks=False)
                        events.append("concurrent_mutation")
                    except BrokerError as error:
                        failures.append(error)
                    finally:
                        completed.set()

                competitor_thread = Thread(target=competitor)

                def boundary(name):
                    events.append(name)
                    if name == "fence":
                        competitor_thread.start()
                        require(attempted.wait(5), "native_gate_assertion")
                        require(not completed.wait(0.1), "concurrent_mutation_crossed_fence")

                receipt = conditional(cache, target, digest(original), output, boundary)
                competitor_thread.join(10)
                require(not competitor_thread.is_alive(), "same_cache_deadlock")
                require(not failures, failures)
                require(
                    events.index("receipt") < events.index("concurrent_mutation"),
                    events,
                )
                require(receipt["after"] == digest(output), "native_gate_assertion")
                require(cache.format(1, "EPUB") == external, "native_gate_assertion")

                try:
                    conditional(cache, target, digest(original), output)
                except ValueError as error:
                    require(str(error) == "source_changed", "native_gate_assertion")
                else:
                    raise AssertionError("changed_source_did_not_refuse")
                require(cache.format(1, "EPUB") == external, "native_gate_assertion")
                conditional(cache, target, digest(external), output)
                require(
                    imports.call_count == postimports.call_count == 0,
                    "native_gate_assertion",
                )
                sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
                import uuid

                from librarium.delivery_broker import Broker, BrokerError

                native = NativeOwner(cache, cache.library_id)
                binding = {
                    "library_uuid": target[0],
                    "book_id": "1",
                    "book_uuid": target[2],
                }
                state = root / "journal"
                state.mkdir(mode=0o700)
                broker = Broker(state, native)
                try:
                    request = {
                        "operation_id": str(uuid.uuid4()),
                        "mode": "delivery",
                        "target": binding,
                        "before": native.observe(binding),
                        "output": {"sha256": digest(original), "size": len(original)},
                    }
                    from calibre.ebooks.metadata.book.base import Metadata

                    other_id = cache.create_book_entry(Metadata("Unrelated", ["Fixture"]))
                    cache.set_field("title", {other_id: "Unrelated edited"})
                    competing, completed = Event(), Event()
                    serialized = []

                    def edit_other():
                        competing.set()
                        with cache.write_lock:
                            serialized.append("edit")
                            cache.set_field("title", {other_id: "Serialized unrelated edit"})
                        completed.set()

                    thread = Thread(target=edit_other)

                    def broker_boundary(stage):
                        serialized.append(stage)
                        if stage == "prepared":
                            thread.start()
                            require(competing.wait(5), "broker_competitor_missing")
                            require(not completed.wait(0.1), "broker_lock_crossed")

                    broker.boundary = broker_boundary
                    applied = broker.execute(request, original)
                    thread.join(10)
                    require(not thread.is_alive(), "broker_competitor_stalled")
                    require(
                        serialized.index("receipt") < serialized.index("edit"),
                        "broker_receipt_order",
                    )
                    broker.boundary = lambda _: None
                    require(applied["classification"] == "applied", applied)
                    require(
                        broker.execute(request, original) == applied,
                        "replay_changed_receipt",
                    )
                    cache.set_field("title", {other_id: "Another unrelated edit"})
                    require(
                        broker.reconcile(request["operation_id"])["classification"] == "applied",
                        "unrelated_edit_diverged",
                    )
                    cancelled = {
                        **request,
                        "operation_id": str(uuid.uuid4()),
                        "before": native.observe(binding),
                    }
                    broker.cancel(cancelled)
                    cache.set_field("title", {other_id: "Unrelated cancellation drift"})
                    require(
                        broker.reconcile(cancelled["operation_id"])["classification"]
                        == "not_applied",
                        "cancelled_diverged",
                    )
                    stale = {
                        **request,
                        "operation_id": str(uuid.uuid4()),
                        "before": native.observe(binding),
                    }
                    cache.set_field("title", {1: "Changed target baseline"})
                    refused = broker.execute(stale, original)
                    require(refused["classification"] == "not_applied", "fence_did_not_seal")
                    require(
                        not broker.db.execute("SELECT * FROM targets").fetchall(),
                        "fence_reserved",
                    )
                    format_path = Path(cache.format_abspath(1, "EPUB"))
                    linked = root / "linked.epub"
                    import os

                    os.link(format_path, linked)
                    try:
                        native.prepare_write(binding, len(output))
                    except BrokerError as error:
                        require(str(error) == "hardlinked_format", "hardlink_wrong_hold")
                    else:
                        raise AssertionError("hardlink_admitted")
                    linked.unlink()
                    cache.set_field("title", {1: "Synthetic later metadata"})
                    undo = {
                        **request,
                        "operation_id": str(uuid.uuid4()),
                        "mode": "undo",
                        "before": native.observe(binding),
                        "output": {"sha256": digest(output), "size": len(output)},
                    }
                    restored = broker.execute(undo, output)
                    require(restored["classification"] == "applied", restored)
                    require(
                        cache.field_for("title", 1) == "Synthetic later metadata",
                        "undo_changed_later_metadata",
                    )
                    require(
                        broker.reconcile(request["operation_id"])["classification"] == "diverged",
                        "drift_not_detected",
                    )
                finally:
                    broker.close()
                from librarium.delivery_broker import Broker

                Path(cache.format_abspath(1, "TXT")).unlink()
                try:
                    native.observe(binding)
                except BrokerError as error:
                    require(str(error) == "format_unavailable", "missing_format_wrong_hold")
                else:
                    raise AssertionError("missing_recorded_format_not_held")
        finally:
            database.close()
        exported = root / "exported"
        oracle(
            "export",
            "1",
            "--to-dir",
            str(exported),
            "--formats",
            "EPUB",
            "--dont-save-cover",
            "--dont-write-opf",
            "--dont-update-metadata",
            "--single-dir",
        )
        require(
            [p.read_bytes() for p in exported.glob("*.epub")] == [output],
            "native_gate_assertion",
        )
    print(
        json.dumps(
            {
                "missing_format_held": True,
                "maintenance_quiesced": True,
                "broker_proved": ["apply", "replay", "undo", "drift"],
                "gate": "passed",
                "runtime": ".".join(map(str, numeric_version)),
                "elapsed_seconds": round(monotonic() - started, 3),
                "proved": [
                    "conditional_replace",
                    "identity_fences",
                    "hooks_disabled",
                    "byte_identical_readback",
                    "same_cache_serialization",
                    "changed_source_refused",
                    "untouched_fields",
                    "oracle_readback",
                ],
            }
        )
    )
