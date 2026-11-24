"""Source-bound declared identity and all-format byte duplicate observations."""

import hashlib
import os
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from django.conf import settings

from librarium import (
    catalogue,
    content_trust,
    direct_library,
    file_inspections,
    package_comparison,
)
from librarium.validation import bounded_text

POLICY = "librarium.book-assessment.v6"
MAX_BOOKS = 10000
MAX_FILES = 20000
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_FINDINGS = 256
SECONDS = 120
SCOPE = (
    "Preserved package declarations support a bibliographic assessment, not content authentication. "
    "Exact-copy observations cover all recorded formats under one library metadata inventory at "
    "the recorded time; differently packaged or semantic duplicates remain unconfirmed. "
    "No source, metadata, navigation or catalogue was changed."
)


class AssessmentError(Exception):
    def __init__(self, message, status=409, code="assessment_unavailable"):
        super().__init__(message)
        self.status = status
        self.code = code


class _BudgetExceeded(Exception):
    pass


@dataclass
class _Budget:
    cancel_check: Callable[[], bool] | None = None
    deadline: float = field(default_factory=lambda: time.monotonic() + SECONDS)
    consumed: int = 0

    def check(self):
        if self.cancel_check is not None and self.cancel_check():
            raise AssessmentError("The book assessment was cancelled")
        if time.monotonic() > self.deadline:
            raise _BudgetExceeded


def _hash_stream(stream, size, budget):
    digest = hashlib.sha256()
    observed = 0
    while True:
        budget.check()
        chunk = stream.read(min(1024 * 1024, size - observed + 1))
        if not chunk:
            break
        observed += len(chunk)
        budget.consumed += len(chunk)
        if budget.consumed > MAX_TOTAL_BYTES:
            raise _BudgetExceeded
        if observed > size:
            raise direct_library.changed()
        digest.update(chunk)
    if observed != size:
        raise direct_library.changed()
    return digest.hexdigest()


def identity(comparison):
    names = comparison["creators"]["status"]
    title = comparison["title"]["status"]
    isbn = comparison["isbn"]
    if not comparison["inspection_complete"]:
        status = "unconfirmed"
    elif "ambiguous" in {names, title, isbn["status"]}:
        status = "ambiguous"
    elif "different" in {names, title, isbn["status"]} or names == "partial":
        status = "conflicting"
    elif title == names == isbn["status"] == "same" and isbn["capture"] == "recorded":
        status = "supported"
    else:
        status = "unconfirmed"
    editions = {
        edition["edition_id"]: edition
        for entry in isbn["entries"]
        for edition in entry.get("editions", [])
        if not edition["disputed"] and edition["work_id"] == comparison["catalogue"]["work_id"]
    }
    edition_id = None
    edition_status = "unconfirmed"
    if status == "supported" and len(editions) == 1:
        edition_id, edition = next(iter(editions.items()))
        if isinstance(edition["format"], str) and edition["format"].casefold() == "epub":
            edition_status = "supported"
        else:
            edition_id = None
    elif status in {"ambiguous", "conflicting"}:
        edition_status = status
    elif len(editions) > 1:
        edition_status = "ambiguous"
    return (
        {
            "status": status,
            "work_id": comparison["catalogue"]["work_id"],
            "basis": "preserved_package_declarations",
            "title": comparison["title"],
            "creators": comparison["creators"],
            "isbn": isbn,
            "content_authentication": "not_assessed",
        },
        {
            "status": edition_status,
            "edition_id": edition_id,
            "candidates": list(editions.values()),
            "basis": "unambiguous_explicit_epub_edition",
            "language_and_content_equivalence": "not_assessed",
        },
    )


def _coverage(reconciliation, origin, pin):
    if reconciliation is None:
        raise AssessmentError("Choose an explicit saved reconciliation")
    report = reconciliation.report
    try:
        books = report["books"]
        inventory = report["inventory"]
        ids = [entry["book"]["id"] for entry in books]
        if (
            reconciliation.catalogue_version != pin["version"]
            or reconciliation.catalogue_sha256 != pin["sha256"]
            or report["catalogue"] != pin
            or not isinstance(inventory["token"], str)
            or not catalogue.DIGEST.fullmatch(inventory["token"])
            or not isinstance(inventory["library_uuid"], str)
            or (origin is not None and inventory["token"] != origin["inventory"])
            or (origin is not None and inventory["library_uuid"] != origin["library_uuid"])
            or not inventory["library_uuid"]
            or type(report["total"]) is not int
            or not 0 <= report["total"] <= MAX_BOOKS
            or len(books) != report["total"]
            or len(set(ids)) != len(ids)
            or any(not isinstance(key, str) or not key for key in ids)
            or (origin is not None and origin["book_id"] not in ids)
        ):
            raise ValueError
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise AssessmentError(
            "The selected reconciliation does not match these sources", code="coverage_mismatch"
        ) from error
    return report, {entry["book"]["id"]: entry for entry in books}


def _same_work_candidates(entries, selected_id, comparison):
    work_id = comparison["catalogue"]["work_id"]
    names = {
        package_comparison.normalized(author["name"])
        for author in comparison["catalogue"]["authors"]
    }
    title = package_comparison.normalized(comparison["catalogue"]["title"])
    candidates = []
    for book_id, entry in entries.items():
        if book_id == selected_id:
            continue
        book = entry["book"]
        basis = []
        matching = entry.get("match", {})
        if matching.get("status") == "matched" and any(
            candidate["work_id"] == work_id
            and candidate["title_status"] == candidate["authors_status"] == "same"
            for candidate in matching.get("candidates", [])
        ):
            basis.append("saved_catalogue_match")
        if (
            isinstance(book.get("title"), str)
            and title
            and package_comparison.normalized(book["title"]) == title
            and isinstance(book.get("authors"), list)
            and all(isinstance(name, str) for name in book["authors"])
            and names
            and {package_comparison.normalized(name) for name in book["authors"]} == names
        ):
            basis.append("title_and_creators")
        if basis:
            candidates.append({"book_id": book_id, "basis": basis})
    return candidates


def _census(origin, entries, budget):
    sources = []
    unreadable = []
    other_formats: list[dict] = []
    other_format_count = 0
    recorded_count = 0
    with direct_library.snapshot(origin["inventory"]) as (db, _, info):
        if info["library_uuid"] != origin["library_uuid"]:
            raise direct_library.changed()
        ids = [
            str(row[0])
            for row in db.execute("SELECT id FROM books ORDER BY id LIMIT ?", (MAX_BOOKS + 1,))
        ]
        if len(ids) > MAX_BOOKS or set(ids) != entries.keys():
            raise AssessmentError("The selected reconciliation no longer covers this inventory")
        for book_id in ids:
            budget.check()
            row = direct_library.record(db, book_id)
            if row["uuid"] != entries[book_id]["book"].get("uuid"):
                raise AssessmentError("The selected reconciliation has a different book identity")
            try:
                formats = direct_library.format_rows(db, book_id)
                recorded_count += len(formats)
                if recorded_count > MAX_FILES:
                    raise AssessmentError("The inventory exceeds the recorded format limit")
                kinds = [value["format"] for value in formats]
                if len(set(kinds)) != len(kinds):
                    raise ValueError
                for value in formats:
                    kind = value["format"]
                    if kind != "EPUB":
                        other_format_count += 1
                        if len(other_formats) < MAX_FINDINGS:
                            other_formats.append({"book_id": book_id, "format": kind})
                    path = direct_library.text(row["path"], 4096) or ""
                    relative = path + "/" + direct_library.format_name(value)
                    direct_library.components(relative)
                    sources.append((book_id, kind, relative))
            except ValueError, TypeError, direct_library.DirectLibraryError:
                unreadable.append({"book_id": book_id, "reason": "format_metadata_unavailable"})
    return info, sources, unreadable, other_formats, other_format_count, recorded_count


def _duplicates(origin, source_size, source_digest, entries, comparison, budget, *, incoming=False):
    info, sources, unreadable, other_formats, other_format_count, recorded_count = _census(
        origin, entries, budget
    )
    same_work = _same_work_candidates(entries, origin["book_id"], comparison)
    exact = []
    hashed = different_size = 0
    complete = not unreadable
    selected = {"status": "not_applicable" if incoming else "unconfirmed", "observed_sha256": None}
    observed = []
    exhausted = False
    with direct_library.directory() as root:
        for book_id, kind, relative in sorted(
            sources, key=lambda item: (item[0], item[1]) != (origin["book_id"], "EPUB")
        ):
            is_origin = book_id == origin["book_id"] and kind == "EPUB"
            try:
                budget.check()
                with direct_library.source_file(root, relative) as (stream, before):
                    signature = direct_library.signature(before)
                    observed.append((book_id, kind, relative, signature))
                    if before.st_size != source_size:
                        if is_origin:
                            selected = {"status": "different_bytes", "observed_sha256": None}
                            complete = False
                        else:
                            different_size += 1
                        continue
                    digest = _hash_stream(stream, source_size, budget)
                    if direct_library.signature(os.fstat(stream.fileno())) != signature:
                        raise direct_library.changed()
                    if is_origin:
                        selected = {
                            "status": "same_bytes"
                            if digest == source_digest
                            else "different_bytes",
                            "observed_sha256": digest,
                        }
                        complete &= digest == source_digest
                    else:
                        hashed += 1
                        if digest == source_digest:
                            exact.append({"book_id": book_id, "format": kind, "sha256": digest})
            except _BudgetExceeded:
                complete = False
                exhausted = True
                break
            except OSError, ValueError, TypeError, direct_library.DirectLibraryError:
                complete = False
                unreadable.append({"book_id": book_id, "reason": "file_unavailable"})
        if not exhausted:
            for book_id, kind, relative, signature in observed:
                is_origin = book_id == origin["book_id"] and kind == "EPUB"
                try:
                    budget.check()
                    with direct_library.source_file(root, relative) as (_, current):
                        if direct_library.signature(current) != signature:
                            raise direct_library.changed()
                except _BudgetExceeded:
                    complete = False
                    exhausted = True
                    break
                except OSError, ValueError, TypeError, direct_library.DirectLibraryError:
                    complete = False
                    unreadable.append({"book_id": book_id, "reason": "file_changed"})
                    exact = [
                        match
                        for match in exact
                        if (match["book_id"], match["format"]) != (book_id, kind)
                    ]
                    if is_origin:
                        selected["status"] = "changed_during_scan"
    with direct_library.snapshot(origin["inventory"]) as (_, _, current):
        if current["library_uuid"] != origin["library_uuid"]:
            raise direct_library.changed()
    if not incoming and selected["status"] != "same_bytes":
        complete = False
    return (
        info,
        selected,
        {
            "complete": complete,
            "scope": "all_recorded_formats",
            "recorded_files": recorded_count,
            "resolved_files": len(sources),
            "epub_files": sum(kind == "EPUB" for _, kind, _ in sources),
            "other_formats": {
                "status": "unconfirmed",
                "byte_comparison": "complete" if complete else "unconfirmed",
                "count": other_format_count,
                "files": other_formats,
                "truncated": other_format_count > len(other_formats),
            },
            "hashed": hashed,
            "different_size": different_size,
            "budget_exhausted": exhausted,
            "bytes_read": budget.consumed,
            "unreadable": unreadable[:MAX_FINDINGS],
            "unreadable_count": len(unreadable),
            "exact_bytes": {
                "status": "found"
                if exact and complete
                else "none_found"
                if complete
                else "unconfirmed",
                "count": len(exact),
                "books": exact[:MAX_FINDINGS],
                "truncated": len(exact) > MAX_FINDINGS,
            },
            "same_work": {
                "status": "possible" if same_work else "unconfirmed",
                "candidates": same_work[:MAX_FINDINGS],
                "count": len(same_work),
                "truncated": len(same_work) > MAX_FINDINGS,
            },
        },
    )


class _CurrentCatalogue:
    """Exact work and edition IDs in the assessment's own catalogue pin; no alias remapping."""

    def __init__(self, db):
        self.db = db

    def work_current(self, work_id):
        try:
            present = self.db.execute("SELECT 1 FROM work WHERE id=?", (work_id,)).fetchone()
            merged = self.db.execute("SELECT 1 FROM id_alias WHERE old_id=?", (work_id,)).fetchone()
        except sqlite3.Error:
            return False
        return present is not None and merged is None

    def edition_work(self, edition_id):
        try:
            row = self.db.execute(
                "SELECT work_id FROM edition WHERE id=?", (edition_id,)
            ).fetchone()
        except sqlite3.Error:
            return None
        return row[0] if row is not None else None


def _authenticate(reference, envelope, job, pin, work_id, checked_at, budget):
    def checkpoint(count):
        budget.check()
        budget.consumed += count
        if budget.consumed > MAX_TOTAL_BYTES:
            raise _BudgetExceeded

    request = {
        "source_sha256": envelope["source_sha256"],
        "source_size": job.input["source_size"],
        "report_sha256": envelope["report_sha256"],
        "catalogue": {"version": pin["version"], "sha256": pin["sha256"], "work_id": work_id},
        "checked_at": checked_at,
    }
    if reference is None:
        return content_trust.authenticate(None, **request)
    try:
        with catalogue.snapshot(
            settings.LIBRARIUM_CATALOGUE_DIR,
            pin["version"],
            pin["sha256"],
            settings.LIBRARIUM_CATALOGUE_FIXTURE,
        ) as (db, _):
            return content_trust.authenticate(
                reference, **request, resolver=_CurrentCatalogue(db), checkpoint=checkpoint
            )
    except _BudgetExceeded:
        result = content_trust.authenticate(None, **request)
        result.update(
            status="unconfirmed",
            reason_codes=["authentication_budget_exhausted"],
            reference_id=reference["reference_id"],
            registry_sha256=reference["registry_sha256"],
            manifest_sha256=reference["manifest_sha256"],
        )
        return result


def assess(
    job,
    version,
    sha256,
    work_id,
    *,
    reconciliation=None,
    cancel_check=None,
    comparison_inspections=(),
    reference=None,
):
    budget = _Budget(cancel_check)
    checked_at = datetime.now(UTC)
    try:
        budget.check()
        if (
            not isinstance(version, str)
            or not catalogue.valid_version(version)
            or not isinstance(sha256, str)
            or not catalogue.DIGEST.fullmatch(sha256)
            or not isinstance(work_id, str)
            or not work_id
            or not bounded_text(work_id, 80)
        ):
            raise AssessmentError("Choose an explicit catalogue pin and work", 400)
        envelope = file_inspections.report(job)
        origin = job.input.get("library_origin")
        if "library_origin" in job.input and (
            not isinstance(origin, dict)
            or set(origin) != {"library_uuid", "book_id", "inventory", "format"}
            or origin["format"] != "EPUB"
            or not isinstance(origin["library_uuid"], str)
            or not origin["library_uuid"]
            or not bounded_text(origin["library_uuid"], 2000)
            or not isinstance(origin["book_id"], str)
            or not isinstance(origin["inventory"], str)
            or not catalogue.DIGEST.fullmatch(origin["inventory"])
        ):
            raise AssessmentError("A preserved native library EPUB origin is required")
        with catalogue.snapshot(
            settings.LIBRARIUM_CATALOGUE_DIR,
            version,
            sha256,
            settings.LIBRARIUM_CATALOGUE_FIXTURE,
        ) as (db, pin):
            comparison = package_comparison.compare(envelope, db, pin, work_id)
        coverage, entries = _coverage(reconciliation, origin, pin)
        scan_origin = origin or {
            "inventory": coverage["inventory"]["token"],
            "library_uuid": coverage["inventory"]["library_uuid"],
            "book_id": None,
        }
        work, edition = identity(comparison)
        inventory, current_bytes, duplicates = _duplicates(
            scan_origin,
            job.input["source_size"],
            envelope["source_sha256"],
            entries,
            comparison,
            budget,
            incoming=origin is None,
        )
        from librarium.duplicate_evidence import compare_inspections

        duplicates["content"] = compare_inspections(
            job, envelope, comparison_inspections, pin, work_id, entries, scan_origin, budget
        )
        authentication = _authenticate(reference, envelope, job, pin, work_id, checked_at, budget)
        budget.check()
        # Only exact bytes of a supported complete reference clear content identity.
        blockers = [
            *(
                []
                if authentication["status"] == "authenticated_reference_match"
                else ["content_identity_unconfirmed"]
            ),
            "semantic_duplicates_unconfirmed",
            "writer_not_authorized",
        ]
        if work["status"] != "supported":
            blockers.append("declared_work_identity_" + work["status"])
        attribution = comparison["source_attribution"]
        if attribution["status"] != "corroborated":
            blockers.append("source_attribution_" + attribution["status"])
        if edition["status"] != "supported":
            blockers.append("declared_edition_identity_" + edition["status"])
        if origin is not None and current_bytes["status"] != "same_bytes":
            blockers.append("library_source_bytes_changed")
        if not duplicates["complete"]:
            blockers.append("duplicate_scan_incomplete")
        if duplicates["exact_bytes"]["count"]:
            blockers.append("exact_byte_duplicates_found")
        if duplicates["same_work"]["count"]:
            blockers.append("possible_same_work_duplicates")
        if duplicates["other_formats"]["count"]:
            blockers.append("other_format_duplicates_unconfirmed")
        if duplicates["content"]["possible_count"]:
            blockers.append("possible_content_duplicates")
        return {
            "schema_version": POLICY,
            "policy_version": POLICY,
            "job_id": envelope["job_id"],
            "source_sha256": envelope["source_sha256"],
            "report_sha256": envelope["report_sha256"],
            "catalogue": pin,
            "reconciliation_key": str(reconciliation.pk),
            "inventory": inventory,
            "library_origin": origin.copy() if origin is not None else None,
            "source_provenance": {
                "kind": "native_library" if origin is not None else "incoming_upload"
            },
            "content_identity": envelope["report"].get("content_evidence"),
            "reference_authentication": authentication,
            "source_attribution": attribution,
            "assessed_at": checked_at.isoformat(),
            "observation": "historical",
            "file_work_identity": work,
            "edition_identity": edition,
            "current_library_bytes": current_bytes,
            "duplicates": duplicates,
            "blockers": blockers,
            "correction_admission": "held",
            "ready": False,
            "scope": SCOPE,
        }
    except _BudgetExceeded:
        raise AssessmentError("The book assessment exceeded its time limit") from None
    except (direct_library.DirectLibraryError, catalogue.CatalogueError) as error:
        raise AssessmentError(
            str(error), error.status, getattr(error, "code", "catalogue_unavailable")
        ) from error


def recheck_delivery_identity(job, version, sha256, work_id, *, reference, cancel_check=None):
    """Re-authenticate one source under current pins without a duplicate census."""
    with catalogue.snapshot(
        settings.LIBRARIUM_CATALOGUE_DIR, fixture=settings.LIBRARIUM_CATALOGUE_FIXTURE
    ) as (_, current):
        if current["version"] != version or current["sha256"] != sha256:
            raise AssessmentError("Catalogue pin superseded", 409, "catalogue_pin_superseded")
    budget = _Budget(cancel_check)
    checked_at = datetime.now(UTC)
    try:
        budget.check()
        envelope = file_inspections.report(job)
        with catalogue.snapshot(
            settings.LIBRARIUM_CATALOGUE_DIR, version, sha256, settings.LIBRARIUM_CATALOGUE_FIXTURE
        ) as (db, pin):
            comparison = package_comparison.compare(envelope, db, pin, work_id)
        work, edition = identity(comparison)
        attribution = comparison["source_attribution"]
        authentication = _authenticate(reference, envelope, job, pin, work_id, checked_at, budget)
        blockers = (
            []
            if authentication["status"] == "authenticated_reference_match"
            else ["content_identity_unconfirmed"]
        )
        for evidence, prefix, passed in (
            (work, "declared_work_identity_", "supported"),
            (edition, "declared_edition_identity_", "supported"),
            (attribution, "source_attribution_", "corroborated"),
        ):
            if evidence["status"] != passed:
                blockers.append(prefix + evidence["status"])
        budget.check()
        return {
            "schema_version": "librarium.delivery-identity.v1",
            "source_sha256": envelope["source_sha256"],
            "report_sha256": envelope["report_sha256"],
            "catalogue": pin,
            "file_work_identity": work,
            "edition_identity": edition,
            "source_attribution": attribution,
            "reference_authentication": authentication,
            "duplicates": "not_rechecked",
            "blockers": blockers,
            "checked_at": checked_at.isoformat(),
        }
    except _BudgetExceeded:
        raise AssessmentError("The identity recheck exceeded its time limit") from None
