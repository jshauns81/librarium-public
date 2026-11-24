"""Explicit whole-library metadata observations; publication follows all source fences."""

import json
import time
import uuid
from functools import lru_cache

from django.conf import settings

from librarium import (
    catalogue,
    direct_library,
    library_matching,
    package_comparison,
    package_identifiers,
)
from librarium.models import LibraryReconciliation

MAX_BOOKS = 10000
MAX_REPORT_BYTES = 32 * 1024 * 1024
SECONDS = 180
POLICY = "librarium.library-reconciliation.v1"
STATUSES = ("matched", "unmatched", "ambiguous", "disagreement", "held")


class ReconciliationError(Exception):
    def __init__(self, message, code="reconciliation_unavailable"):
        super().__init__(message)
        self.code = code


def request_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise ReconciliationError("Use a valid request or previous-report UUID") from error


def check_replay(saved, version, sha256, previous):
    if (saved.catalogue_version, saved.catalogue_sha256, saved.previous_key) != (
        version,
        sha256,
        previous,
    ):
        raise ReconciliationError("This request key already names different reconciliation inputs")
    return saved


def read(request_key):
    try:
        return LibraryReconciliation.objects.get(pk=request_uuid(request_key))
    except LibraryReconciliation.DoesNotExist as error:
        raise ReconciliationError("The selected saved reconciliation does not exist") from error


def inventory():
    entries = []
    size = 0
    with direct_library.snapshot() as (db, root, info):
        if not info["library_uuid"]:
            raise ReconciliationError("A recorded library UUID is required for reconciliation")
        ids = db.execute("SELECT id FROM books ORDER BY id LIMIT ?", (MAX_BOOKS + 1,)).fetchall()
        if len(ids) > MAX_BOOKS:
            raise ReconciliationError("The library exceeds the reconciliation book limit")
        if len({str(row[0]) for row in ids}) != len(ids):
            raise ReconciliationError("The library has duplicate book record identities")
        for row in ids:
            book_id = str(row[0])
            # Validate the key outside per-book holds so invalid inventory identities fail the scan.
            source = direct_library.record(db, book_id)
            try:
                book = direct_library.project(db, root, source, info, read_files=False)
                book["library_path"] = direct_library.text(source["path"], 4096)
                direct_library.components(book["library_path"])
                entries.append({"book": book})
            except ValueError, TypeError, direct_library.DirectLibraryError:
                entries.append(
                    {
                        "book": {"id": book_id, "uuid": None},
                        "status": "held",
                        "reason": "metadata_or_matching_limit",
                    }
                )
            size += len(json.dumps(entries[-1], ensure_ascii=True).encode())
            if size > MAX_REPORT_BYTES:
                raise ReconciliationError("Reconciliation exceeds the saved report limit")
    return info, entries


def changes(previous, info, entries):
    if previous is None:
        return None
    if previous.report["inventory"]["library_uuid"] != info["library_uuid"]:
        raise ReconciliationError("The previous report belongs to a different library")
    return compare(
        {entry["book"]["id"]: entry["book"] for entry in previous.report["books"]},
        {entry["book"]["id"]: entry["book"] for entry in entries},
    )


def compare(old, new):
    """Book-by-book differences between two observations, keyed by Calibre book id."""
    shared = old.keys() & new.keys()
    unknown = {key for key in shared if not old[key]["uuid"] or not new[key]["uuid"]}
    replaced = {key for key in shared - unknown if old[key]["uuid"] != new[key]["uuid"]}
    return {
        "added": sorted(new.keys() - old.keys(), key=int),
        "removed": sorted(old.keys() - new.keys(), key=int),
        "replaced": sorted(replaced, key=int),
        "identity_unknown": sorted(unknown, key=int),
        "changed": sorted(
            (key for key in shared - replaced - unknown if old[key] != new[key]), key=int
        ),
    }


def build_report(
    request_key, version, sha256, *, previous=None, expected_inventory=None, cancel_check=None
):
    key = request_uuid(request_key)
    prior_key = request_uuid(previous) if previous is not None else None
    if (
        not isinstance(version, str)
        or not catalogue.valid_version(version)
        or not isinstance(sha256, str)
        or not catalogue.DIGEST.fullmatch(sha256)
        or prior_key == key
    ):
        raise ReconciliationError("Select an explicit catalogue pin and a distinct previous report")
    prior = read(prior_key) if prior_key is not None else None
    started = time.monotonic()
    deadline = started + SECONDS
    try:
        observed, entries = inventory()
        if expected_inventory is not None and any(
            observed[field] != expected_inventory[field] for field in ("token", "library_uuid")
        ):
            raise ReconciliationError("The selected library inventory changed", "library_changed")
        delta = changes(prior, observed, entries)
        counts = dict.fromkeys(STATUSES, 0)
        size = 0
        normalize = lru_cache(maxsize=32768)(package_comparison.normalized)
        normalize_isbn = lru_cache(maxsize=32768)(package_identifiers._catalogue_isbn)
        with catalogue.snapshot(
            settings.LIBRARIUM_CATALOGUE_DIR,
            version,
            sha256,
            settings.LIBRARIUM_CATALOGUE_FIXTURE,
            seconds=max(0, deadline - time.monotonic()),
        ) as (db, pin):
            for entry in entries:
                if cancel_check is not None and cancel_check():
                    raise ReconciliationError("The reconciliation attempt was interrupted")
                if time.monotonic() > deadline:
                    raise ReconciliationError("Reconciliation exceeded its time limit")
                if entry.get("status") != "held":
                    try:
                        entry["match"] = library_matching.match(
                            entry["book"],
                            db,
                            pin,
                            observed,
                            normalize=normalize,
                            normalize_isbn=normalize_isbn,
                        )
                        entry["status"] = entry["match"]["status"]
                    except catalogue.CatalogueError as error:
                        if error.status != 422:
                            raise
                        entry.update(status="held", reason="metadata_or_matching_limit")
                counts[entry["status"]] += 1
                size += len(json.dumps(entry, ensure_ascii=True).encode())
                if size > MAX_REPORT_BYTES:
                    raise ReconciliationError("Reconciliation exceeds the saved report limit")
        # Matching uses captured metadata outside the library reader lock; recheck its source now.
        with direct_library.snapshot(observed["token"]) as (_, _, current):
            if current["library_uuid"] != observed["library_uuid"]:
                raise direct_library.changed()
        if time.monotonic() > deadline:
            raise ReconciliationError("Reconciliation exceeded its time limit")
        report = {
            "schema_version": POLICY,
            "policy_version": POLICY,
            "request_key": str(key),
            "previous": str(prior_key) if prior_key else None,
            "inventory": observed,
            "catalogue": pin,
            "total": len(entries),
            "counts": counts,
            "books": entries,
            "changes": delta,
            "file_identity": "not_assessed",
            "duplicates": "not_assessed",
            "ready": False,
            "scope": library_matching.SCOPE,
        }
        if len(json.dumps(report, ensure_ascii=True).encode()) > MAX_REPORT_BYTES:
            raise ReconciliationError("Reconciliation exceeds the saved report limit")
        if time.monotonic() > deadline:
            raise ReconciliationError("Reconciliation exceeded its time limit")
    except (direct_library.DirectLibraryError, catalogue.CatalogueError) as error:
        raise ReconciliationError(
            str(error), getattr(error, "code", "catalogue_unavailable")
        ) from error
    return report


def save_report(report):
    saved, _ = LibraryReconciliation.objects.get_or_create(
        request_key=request_uuid(report["request_key"]),
        defaults={
            "catalogue_version": report["catalogue"]["version"],
            "catalogue_sha256": report["catalogue"]["sha256"],
            "previous_key": request_uuid(report["previous"]) if report["previous"] else None,
            "report": report,
        },
    )
    return check_replay(
        saved,
        report["catalogue"]["version"],
        report["catalogue"]["sha256"],
        request_uuid(report["previous"]) if report["previous"] else None,
    )


def reconcile(request_key, version, sha256, *, previous=None):
    key = request_uuid(request_key)
    prior_key = request_uuid(previous) if previous is not None else None
    saved = LibraryReconciliation.objects.filter(pk=key).first()
    if saved is not None:
        return check_replay(saved, version, sha256, prior_key)
    return save_report(build_report(key, version, sha256, previous=prior_key))
