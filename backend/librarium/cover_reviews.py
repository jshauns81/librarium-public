"""Explicit, resumable read-only census and PostgreSQL-owned cover review state.

Library UUID plus Calibre book UUID owns the review: restoring or re-importing
the same UUID intentionally inherits its skip, even with a different numeric ID.
"""

import atexit
import hashlib
import json
import os
import time
import uuid
from concurrent.futures import ALL_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import timedelta
from threading import Event
from types import SimpleNamespace

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count, Exists, OuterRef, Q, TextField, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from librarium import cover_facts, direct_library, library_read_model
from librarium.models import (
    CalibreBook,
    CalibreIdentifier,
    CoverCensus,
    CoverReviewAction,
    CoverReviewEntry,
    LibraryReadModel,
)

LOCK = 0x434F5631
BATCH_SIZE = 64
OBSERVATION_CHUNK_SIZE = 8
SLICE_SECONDS = 12.0
OBSERVATION_GRACE_SECONDS = 0.25
LEASE_SECONDS = 45
_observation_pool: ThreadPoolExecutor | None = None
_pool_workers = 0
_inflight: set[Future] = set()
_interruptions: set[Event] = set()


def shutdown_observations():
    global _observation_pool
    for event in _interruptions:
        event.set()
    if _observation_pool is not None:
        _observation_pool.shutdown(wait=True, cancel_futures=True)
        _observation_pool = None
    _inflight.clear()
    _interruptions.clear()


atexit.register(shutdown_observations)


def observation_pool(workers):
    global _observation_pool, _pool_workers
    _inflight.difference_update(future for future in tuple(_inflight) if future.done())
    # Never build a queue behind a child still stopping from an earlier slice.
    if _inflight:
        return None
    _interruptions.clear()
    if _observation_pool is not None and workers != _pool_workers:
        shutdown_observations()
    if _observation_pool is None:
        _observation_pool = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="cover-census"
        )
        _pool_workers = workers
    return _observation_pool


class ReviewError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(
            {
                "unavailable": "Refresh the library before checking covers.",
                "conflict": "This review changed. Refresh it before continuing.",
                "busy": "A cover census is already running.",
                "missing": "This cover review is no longer available.",
                "invalid": "Use valid cover review parameters.",
            }.get(code, "The cover review is unavailable.")
        )


def request_uuid(value):
    if not isinstance(value, str):
        raise ReviewError("invalid", 400)
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise ReviewError("invalid", 400) from None
    if str(parsed) != value:
        raise ReviewError("invalid", 400)
    return parsed


def read_model(*, lock=False):
    rows = LibraryReadModel.objects.select_for_update() if lock else LibraryReadModel.objects
    model = rows.filter(pk=1).first()
    if (
        settings.LIBRARY_READ_MODEL == "off"
        or not settings.DIRECT_LIBRARY_ROOT
        or model is None
        or model.stale
        or not model.token
        or not model.library_uuid
        or model.root != settings.DIRECT_LIBRARY_ROOT
    ):
        raise ReviewError("unavailable", 503)
    return model


@transaction.atomic
def start(key):
    key = request_uuid(key)
    # The read-model publisher uses the same lock; its replace-all rows stay consistent.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [library_read_model.LOCK])
    model = read_model(lock=True)
    prior = CoverCensus.objects.filter(request_key=key).first()
    if prior:
        return prior
    if CoverCensus.objects.filter(
        library_uuid=model.library_uuid, state__in=["pending", "running"]
    ).exists():
        raise ReviewError("busy")
    retire_invalid(model.library_uuid)
    total = CalibreBook.objects.count()
    return CoverCensus.objects.create(
        request_key=key,
        library_uuid=model.library_uuid,
        inventory_token=model.token,
        detector=cover_facts.POLICY,
        total=total,
        remaining=total,
    )


def census_data(row):
    if row is None:
        return None
    return {
        "id": str(row.pk),
        "library_uuid": row.library_uuid,
        "inventory": row.inventory_token,
        "detector": row.detector,
        "state": row.state,
        "cursor": row.cursor,
        "total": row.total,
        "scanned": row.scanned,
        "remaining": row.remaining,
        "unresolved": row.unresolved,
        "error": row.error,
        "identity_issues": row.identity_issues,
        "identity_issue_count": row.identity_issue_count,
        "complete": row.state == "complete",
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


@transaction.atomic
def cancel(census_id):
    row = CoverCensus.objects.select_for_update().filter(pk=census_id).first()
    if row is None:
        raise ReviewError("missing", 404)
    if row.state in {"pending", "running"}:
        row.state, row.lease_token, row.lease_until = "cancelled", None, None
        row.finished_at = timezone.now()
        row.save()
    return census_data(row)


@contextmanager
def worker_lock():
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK])
        acquired = cursor.fetchone()[0]
    try:
        yield acquired
    finally:
        if acquired:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK])


def source_facts(book, previous=None, *, decode=True):
    signature = ""
    try:
        with (
            direct_library.directory() as root,
            direct_library.folder(root, direct_library.components(book.path)) as parent,
        ):
            try:
                info = os.stat("cover.jpg", dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                return {
                    **cover_facts.unknown(""),
                    "status": "known",
                    "reasons": ["missing"],
                }, "absent"
            signature = library_read_model.signed(info)
            if info.st_size > cover_facts.MAX_BYTES:
                return cover_facts.unknown("oversize"), signature
            with direct_library.file_in(parent, "cover.jpg", cover_facts.MAX_BYTES) as (
                stream,
                before,
            ):
                if library_read_model.signed(before) != signature:
                    raise ValueError
                raw = stream.read(cover_facts.MAX_BYTES + 1)
                if (
                    len(raw) != before.st_size
                    or library_read_model.signed(os.fstat(stream.fileno())) != signature
                ):
                    raise ValueError
            if (
                previous
                and previous.source_signature == signature
                and previous.facts.get("detector") == cover_facts.POLICY
                and previous.facts.get("status") == "known"
                and previous.facts.get("sha256") == hashlib.sha256(raw).hexdigest()
            ):
                return previous.facts, signature
            return (cover_facts.inspect_cover(raw) if decode else raw), signature
    except OSError, ValueError, TypeError, direct_library.DirectLibraryError:
        return cover_facts.unknown("unreadable"), signature


def pinned_facts(captured, interrupted):
    """Only captured bytes/facts and an interruption callback enter decoder threads."""
    facts = (
        cover_facts.inspect_cover(captured, interrupted=interrupted)
        if isinstance(captured, bytes)
        else captured
    )
    # Transport failure or interruption is not an observation of the cover.
    return None if interrupted() or facts.get("error") == "inspection_failed" else facts


def source_matches(book, signature, facts):
    if source_signature(book) != signature:
        return False
    if facts.get("sha256"):
        captured, current = source_facts(book, decode=False)
        return (
            current == signature
            and isinstance(captured, bytes)
            and hashlib.sha256(captured).hexdigest() == facts["sha256"]
        )
    return True


def source_signature(book):
    try:
        with (
            direct_library.directory() as root,
            direct_library.folder(root, direct_library.components(book.path)) as parent,
        ):
            try:
                return library_read_model.signed(
                    os.stat("cover.jpg", dir_fd=parent, follow_symlinks=False)
                )
            except FileNotFoundError:
                return "absent"
    except OSError, ValueError, TypeError, direct_library.DirectLibraryError:
        return ""


def validation_books(census, limit):
    """Resume a bounded validation batch without replacing the serving inventory."""
    return list(
        observed_books(census).filter(pk__gt=census.validation_cursor).order_by("pk")[:limit]
    )


def fingerprint(facts, signature):
    return hashlib.sha256(json.dumps([signature, facts], sort_keys=True).encode()).hexdigest()


def invalid_books():
    duplicates = (
        CalibreBook.objects.values("uuid").annotate(n=Count("uuid")).filter(n__gt=1).values("uuid")
    )
    return CalibreBook.objects.filter(Q(uuid__isnull=True) | Q(uuid="") | Q(uuid__in=duplicates))


def retire_invalid(library_uuid):
    valid = CalibreBook.objects.exclude(pk__in=invalid_books().values("pk"))
    CoverReviewEntry.objects.filter(library_uuid=library_uuid).exclude(
        book_uuid__in=valid.values("uuid")
    ).update(present=False)


def observed_books(census):
    rows = CoverReviewEntry.objects.filter(
        library_uuid=census.library_uuid,
        book_uuid=OuterRef("uuid"),
        calibre_id=OuterRef("pk"),
        observed_census=census.pk,
        observed_inventory_signature=OuterRef("review_signature"),
        present=True,
    )
    return CalibreBook.objects.exclude(pk__in=invalid_books().values("pk")).annotate(
        review_signature=Coalesce("cover_signature", Value("absent"), output_field=TextField()),
        review_observed=Exists(rows),
    )


def recount(census):
    """Counts describe the current inventory, including changes behind the cursor."""
    retire_invalid(census.library_uuid)
    invalid = invalid_books().filter(pk__lte=census.cursor).order_by("pk")
    census.identity_issue_count = invalid.count()
    census.identity_issues = [
        {"book_id": str(book_id), "error": "identity_unknown"}
        for book_id in invalid.values_list("pk", flat=True)[:100]
    ]
    observed = observed_books(census).filter(review_observed=True)
    census.total = CalibreBook.objects.count()
    census.scanned = observed.count() + census.identity_issue_count
    census.remaining = census.total - census.scanned
    census.unresolved = (
        census.identity_issue_count
        + CoverReviewEntry.objects.filter(
            library_uuid=census.library_uuid,
            observed_census=census.pk,
            present=True,
            book_uuid__in=observed.values("uuid"),
            facts__status="unresolved",
        ).count()
    )


@transaction.atomic
def publish(census_id, lease, book, facts, signature, *, identity_error=False):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [library_read_model.LOCK])
    census = CoverCensus.objects.select_for_update().get(pk=census_id)
    if census.state != "running" or census.lease_token != lease:
        return False
    try:
        model = read_model(lock=True)
        valid = model.library_uuid == census.library_uuid
    except ReviewError:
        return False
    if not valid:
        partial(census, "inventory_changed")
        return False
    if not CalibreBook.objects.filter(pk=book.pk, uuid=book.uuid, path=book.path).exists():
        return False
    if not identity_error:
        row, created = CoverReviewEntry.objects.select_for_update().get_or_create(
            library_uuid=census.library_uuid,
            book_uuid=book.uuid,
            defaults={"calibre_id": book.pk},
        )
        new_fingerprint = fingerprint(facts, signature)
        if not created and row.fingerprint != new_fingerprint:
            row.revision += 1
        healthy = facts.get("status") == "known" and facts.get("reasons") == []
        if row.state == "done" and not healthy:
            row.state = "todo"
        elif (
            row.state == "todo"
            and not created
            and healthy
            and (row.facts.get("reasons") or row.facts.get("status") == "unresolved")
        ):
            row.state = "done"
        row.calibre_id, row.title = book.pk, book.title
        row.source_signature, row.fingerprint, row.facts, row.present = (
            signature,
            new_fingerprint,
            facts,
            True,
        )
        row.changed_since_skipped = (
            row.state == "skipped" and row.skipped_fingerprint != new_fingerprint
        )
        row.observed_census = census.pk
        row.observed_inventory_signature = book.cover_signature or "absent"
        row.save()
    census.cursor = max(census.cursor, book.pk)
    census.lease_until = timezone.now() + timedelta(seconds=LEASE_SECONDS)
    census.save()
    return True


def partial(census, error):
    census.state, census.error = "partial", error
    census.lease_token = census.lease_until = None
    census.finished_at = timezone.now()
    census.save()


def observe_chunk(census, lease, books, invalid_ids, validating, deadline, pool):
    if library_read_model.current_token() != census.inventory_token:
        return []
    # Leave time for interruption, the full metadata fence and ordered publication.
    observation_deadline = deadline - min(1.0, SLICE_SECONDS / 4)
    pending = []
    interrupted = Event()
    _interruptions.add(interrupted)
    futures: set[Future] = set()
    try:
        for book in books:
            if time.monotonic() >= observation_deadline:
                break
            invalid_identity = book.pk in invalid_ids
            previous = (
                CoverReviewEntry.objects.filter(
                    library_uuid=census.library_uuid, book_uuid=book.uuid
                ).first()
                if not invalid_identity
                else None
            )
            if (
                validating
                and getattr(book, "review_observed", False)
                and previous is not None
                and previous.facts.get("error") != "inspection_failed"
                and source_matches(book, previous.source_signature, previous.facts)
            ):
                pending.append((book, None, "", False))
                continue
            captured, signature = (
                source_facts(book, previous, decode=False)
                if not invalid_identity
                else (cover_facts.unknown("identity_unknown"), "")
            )
            if time.monotonic() >= observation_deadline:
                break
            future = pool.submit(
                pinned_facts,
                captured,
                lambda: interrupted.is_set() or time.monotonic() >= deadline,
            )
            futures.add(future)
            _inflight.add(future)
            pending.append((book, future, signature, invalid_identity))
        remaining = futures
        while remaining:
            budget = observation_deadline - time.monotonic()
            if not CoverCensus.objects.filter(
                pk=census.pk, state="running", lease_token=lease
            ).exists():
                return []
            if budget <= 0:
                prefix = []
                for item in pending:
                    future = item[1]
                    if future is not None and (not future.done() or future.cancelled()):
                        break
                    prefix.append(item)
                pending = prefix
                interrupted.set()
                break
            _, remaining = wait(remaining, timeout=min(0.05, budget), return_when=ALL_COMPLETED)
        # Full database/WAL/journal fences enclose every result admitted for publication.
        if library_read_model.current_token() != census.inventory_token:
            return []
        return pending
    finally:
        interrupted.set()
        for future in futures:
            future.cancel()
        if futures:
            wait(futures, timeout=OBSERVATION_GRACE_SECONDS)
        _inflight.difference_update(future for future in futures if future.done())
        if all(future.done() for future in futures):
            _interruptions.discard(interrupted)


def tick(*, batch_size=BATCH_SIZE):
    """Process only explicitly requested censuses. A dead worker's lease is reclaimable."""
    with worker_lock() as acquired:
        if not acquired:
            return False
        with transaction.atomic():
            census = (
                CoverCensus.objects.select_for_update()
                .filter(state__in=["pending", "running"])
                .order_by("created_at")
                .first()
            )
            if census is None:
                return False
            if census.lease_until and census.lease_until > timezone.now():
                return False
            lease = uuid.uuid4()
            census.state, census.lease_token = "running", lease
            census.lease_until = timezone.now() + timedelta(seconds=LEASE_SECONDS)
            census.save()
        try:
            library_read_model.tick(raise_errors=True)
            failed = LibraryReadModel.objects.filter(pk=1, stale=True).first()
            if failed and failed.error and settings.LIBRARY_READ_MODEL != "off":
                raise library_read_model.ReadModelError(failed.error)
            model = read_model()
            if model.library_uuid != census.library_uuid:
                raise ReviewError("conflict")
            if model.token != census.inventory_token and census.validation_cursor:
                changed_book = (
                    observed_books(census)
                    .filter(pk__lte=census.validation_cursor, review_observed=False)
                    .order_by("pk")
                    .first()
                )
                if changed_book is not None:
                    census.validation_cursor = max(0, changed_book.pk - 1)
            census.inventory_token = model.token
            deadline = time.monotonic() + SLICE_SECONDS
            books = list(
                CalibreBook.objects.filter(pk__gt=census.cursor).order_by("pk")[
                    : max(1, min(batch_size, 100))
                ]
            )
            validating = not books
            if validating:
                books = validation_books(census, max(1, min(batch_size, 100)))
            else:
                census.validation_cursor = 0
            invalid_ids = set(
                invalid_books()
                .filter(pk__in=[book.pk for book in books])
                .values_list("pk", flat=True)
            )
            workers = settings.COVER_CENSUS_OBSERVATION_WORKERS
            pool = observation_pool(workers)
            if pool is not None:
                stopped = False
                for offset in range(0, len(books), OBSERVATION_CHUNK_SIZE):
                    if time.monotonic() >= deadline:
                        break
                    chunk = books[offset : offset + OBSERVATION_CHUNK_SIZE]
                    pending = observe_chunk(
                        census,
                        lease,
                        chunk,
                        invalid_ids,
                        validating,
                        deadline,
                        pool,
                    )
                    if not pending:
                        break
                    for book, future, signature, invalid_identity in pending:
                        if future is None:
                            census.validation_cursor = book.pk
                            continue
                        facts = future.result()
                        if (
                            facts is None
                            or (not invalid_identity and not source_matches(book, signature, facts))
                            or not publish(
                                census.pk,
                                lease,
                                book,
                                facts,
                                signature,
                                identity_error=invalid_identity,
                            )
                        ):
                            stopped = True
                            break
                        if validating:
                            census.validation_cursor = book.pk
                    if stopped or len(pending) < len(chunk):
                        break
            fresh = library_read_model.current_token() == census.inventory_token
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [library_read_model.LOCK])
                current = CoverCensus.objects.select_for_update().get(pk=census.pk)
                if current.state == "running" and current.lease_token == lease:
                    latest = read_model(lock=True)
                    if latest.library_uuid != current.library_uuid:
                        partial(current, "inventory_changed")
                        return True
                    current.inventory_token = census.inventory_token
                    current.validation_cursor = census.validation_cursor
                    recount(current)
                    current.lease_token = current.lease_until = None
                    current.error = ""
                    if (
                        validating
                        and not books
                        and fresh
                        and latest.token == census.inventory_token
                        and current.remaining == 0
                    ):
                        current.state = "partial" if current.unresolved else "complete"
                        current.finished_at = timezone.now()
                    current.save()
        except (
            ReviewError,
            direct_library.DirectLibraryError,
            OSError,
            ValueError,
            library_read_model.ReadModelError,
        ) as error:
            with transaction.atomic():
                current = CoverCensus.objects.select_for_update().get(pk=census.pk)
                if current.state == "running" and current.lease_token == lease:
                    cause = (
                        error.__cause__
                        if isinstance(error, library_read_model.ReadModelError)
                        else error
                    )
                    changed = (isinstance(cause, ReviewError) and cause.code == "conflict") or (
                        isinstance(cause, direct_library.DirectLibraryError) and cause.status == 409
                    )
                    label = "inventory_changed" if changed else "unavailable"
                    if isinstance(error, ReviewError) and error.code == "conflict":
                        partial(current, label)
                    else:
                        current.error = label
                        current.validation_cursor = census.validation_cursor
                        current.lease_token = current.lease_until = None
                        current.save()
        return True


def entry_data(row, authors=None, *, selection_pending=False, isbn=None):
    return {
        "selection_pending": selection_pending,
        "id": str(row.pk),
        "library_uuid": row.library_uuid,
        "book_uuid": row.book_uuid,
        "book_id": str(row.calibre_id),
        "title": row.title,
        "isbn": isbn
        if isbn is not None
        else (
            CalibreIdentifier.objects.filter(
                book_id=row.calibre_id, book__uuid=row.book_uuid, type="isbn"
            )
            .order_by("position")
            .values_list("value", flat=True)
            .first()
            or ""
        ),
        "authors": authors
        if authors is not None
        else list(
            CalibreBook.objects.filter(pk=row.calibre_id, uuid=row.book_uuid)
            .values_list("author_links__author__name", flat=True)
            .order_by("author_links__position")
            .exclude(author_links__author__name__isnull=True)
        ),
        "revision": row.revision,
        "state": row.state,
        "facts": row.facts,
        "changed_since_skipped": row.changed_since_skipped,
        "cover_url": f"/api/cover-reviews/{row.pk}/cover" if row.facts.get("media_type") else None,
    }


@contextmanager
def current_entry(row, *, wait=False):
    model = read_model()
    if model.library_uuid != row.library_uuid or not row.present:
        raise ReviewError("conflict")
    with direct_library.snapshot(wait=wait) as (db, root, info):
        matches = db.execute(
            "SELECT id FROM books WHERE uuid=? LIMIT 2", [row.book_uuid]
        ).fetchall()
        if info["library_uuid"] != row.library_uuid or len(matches) != 1:
            raise ReviewError("conflict")
        book = direct_library.record(db, str(matches[0][0]))
        facts, signature = source_facts(SimpleNamespace(path=book["path"]), row)
        if signature != row.source_signature or facts != row.facts:
            raise ReviewError("conflict")
        if facts.get("sha256") and facts.get("media_type"):
            raw, _ = direct_library.read_cover(root, book["path"], limit=cover_facts.MAX_BYTES)
            if hashlib.sha256(raw).hexdigest() != facts["sha256"]:
                raise ReviewError("conflict")
        yield root, book


def replay(key, entry_id, revision, skipped, actor):
    previous = CoverReviewAction.objects.filter(pk=key).first()
    if previous:
        if (previous.entry_id, previous.expected_revision, previous.skipped, previous.actor) != (
            entry_id,
            revision,
            skipped,
            actor,
        ):
            raise ReviewError("conflict")
        return previous.result
    return None


def metadata_signature():
    with direct_library.directory() as root:
        result = [direct_library.signature(os.fstat(root))[:2]]
        for name in ("metadata.db", "metadata.db-wal", "metadata.db-journal"):
            try:
                result.append(
                    direct_library.signature(os.stat(name, dir_fd=root, follow_symlinks=False))
                )
            except FileNotFoundError:
                result.append(None)
        return result


def set_skip(entry_id, revision, skipped, key, actor):
    key = request_uuid(key)
    if type(revision) is not int or not 1 <= revision < 2**63 or type(skipped) is not bool:
        raise ReviewError("invalid", 400)
    previous = replay(key, entry_id, revision, skipped, actor)
    if previous is not None:
        return previous
    row = CoverReviewEntry.objects.filter(pk=entry_id).first()
    if row is None:
        raise ReviewError("missing", 404)
    if row.revision != revision or not skippable(row):
        previous = replay(key, entry_id, revision, skipped, actor)
        if previous is not None:
            return previous
        raise ReviewError("conflict")
    metadata = metadata_signature()
    with current_entry(row, wait=True) as (_, book):
        path = book["path"]
    from librarium.cover_candidates import pending_selections

    selection_pending = pending_selections([row], read_model())[row.pk]
    # The snapshot, hashing and decoder have all finished before taking database locks.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK + 1])
        previous = replay(key, entry_id, revision, skipped, actor)
        if previous is not None:
            return previous
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [library_read_model.LOCK])
        model = read_model(lock=True)
        current = CoverReviewEntry.objects.select_for_update().get(pk=entry_id)
        if (
            model.library_uuid != row.library_uuid
            or not current.present
            or current.revision != revision
            or not skippable(current)
            or current.fingerprint != row.fingerprint
            or current.source_signature != row.source_signature
            or current.calibre_id != row.calibre_id
            or metadata_signature() != metadata
            or source_signature(SimpleNamespace(path=path)) != row.source_signature
        ):
            raise ReviewError("conflict")
        row = current
        row.state = (
            "skipped"
            if skipped
            else (
                "done"
                if row.facts.get("status") == "known" and row.facts.get("reasons") == []
                else "todo"
            )
        )
        row.skipped_fingerprint = row.fingerprint if skipped else ""
        row.changed_since_skipped = False
        row.revision += 1
        row.save()
        result = entry_data(row, selection_pending=selection_pending)
        CoverReviewAction.objects.create(
            request_key=key,
            entry=row,
            expected_revision=revision,
            skipped=skipped,
            actor=actor,
            result=result,
        )
    return result


def skippable(row):
    return row.state == "skipped" or (
        row.state == "todo"
        and (row.facts.get("status") == "unresolved" or bool(row.facts.get("reasons")))
    )
