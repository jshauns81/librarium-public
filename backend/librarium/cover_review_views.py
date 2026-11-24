"""Authenticated read-only cover queue; the only book action records a shared skip."""

import hashlib
import math

from django.conf import settings
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Q, Value, When
from django.http import HttpResponse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from librarium import (
    catalogue,
    catalogue_covers,
    cover_candidates,
    cover_facts,
    cover_reviews,
    direct_library,
    library_matching,
)
from librarium.delivery_writer import WriterError, parse
from librarium.models import CalibreBookAuthor, CalibreIdentifier, CoverCensus, CoverReviewEntry
from librarium.operator_identity import principal
from librarium.views import response

PAGE_SIZE = 24


def endpoint(request, action):
    if not principal(request):
        reply = response(
            {"error": "Authenticate an operator to review covers.", "code": "reviewer_required"},
            401,
        )
    else:
        try:
            reply = action()
        except cover_reviews.ReviewError as error:
            reply = response({"error": str(error), "code": error.code}, error.status)
        except ValueError, TypeError, UnicodeError, WriterError:
            reply = response(
                {"error": "Use valid cover review parameters.", "code": "invalid"}, 400
            )
        except direct_library.DirectLibraryError as error:
            reply = response(
                {"error": "Refresh the library before reading this cover.", "code": error.code},
                error.status,
            )
        except catalogue.CatalogueError as error:
            reply = response(
                {
                    "error": "Catalogue suggestions unavailable. Refresh the catalogue and retry.",
                    "code": "snapshot_changed" if error.status == 409 else "catalogue_unavailable",
                },
                error.status,
            )
        except OSError:
            reply = response(
                {"error": "This library cover is unavailable.", "code": "unreadable"}, 404
            )
    reply["Cache-Control"] = "no-store"
    return reply


def parameters(request, allowed):
    if set(request.GET) - allowed or any(len(request.GET.getlist(k)) != 1 for k in request.GET):
        raise ValueError


def body(request, keys, optional=frozenset()):
    parameters(request, set())
    if request.content_type != "application/json":
        raise cover_reviews.ReviewError("invalid", 415)
    raw = request.read(4097)
    if len(raw) > 4096:
        raise cover_reviews.ReviewError("invalid", 413)
    value = parse(raw)
    if type(value) is not dict or set(value) - keys - optional or keys - set(value):
        raise ValueError
    return value


@require_GET
def queue(request):
    def action():
        parameters(request, {"state", "reason", "page"})
        state = request.GET.get("state", "todo")
        reason = request.GET.get("reason", "")
        page_text = request.GET.get("page", "1")
        if (
            state not in {"todo", "done", "skipped"}
            or reason not in ("", "small", "unresolved", *cover_facts.REASONS)
            or not page_text.isascii()
            or not page_text.isdecimal()
            or len(page_text) > 5
            or not 1 <= int(page_text) <= 10000
            or str(int(page_text)) != page_text
        ):
            raise ValueError
        page = int(page_text)
        with cover_reviews.library_read_model.consistent():
            model = cover_reviews.read_model()
            census = (
                CoverCensus.objects.filter(library_uuid=model.library_uuid)
                .order_by("-created_at")
                .first()
            )
            rows = CoverReviewEntry.objects.filter(library_uuid=model.library_uuid, present=True)
            rows = rows.filter(
                Exists(
                    cover_reviews.library_read_model.CalibreBook.objects.filter(
                        pk=OuterRef("calibre_id"), uuid=OuterRef("book_uuid")
                    )
                )
            )
            actionable = Q(facts__status="unresolved") | ~Q(facts__reasons=[])
            rows = rows.filter(~Q(state="todo") | actionable)
            counts = {"todo": 0, "done": 0, "skipped": 0}
            counts.update(
                {row["state"]: row["n"] for row in rows.values("state").annotate(n=Count("id"))}
            )
            rows = rows.filter(state=state)
            if reason == "small":
                rows = rows.filter(
                    Q(facts__reasons__contains=["width_below_1000"])
                    | Q(facts__reasons__contains=["height_below_1200"])
                )
            elif reason == "unresolved":
                rows = rows.filter(facts__status="unresolved")
            elif reason:
                rows = rows.filter(facts__reasons__contains=[reason])
            elif state == "todo":
                rows = rows.filter(Q(facts__status="unresolved") | ~Q(facts__reasons=[]))
            total = rows.count()
            entries = list(
                rows.annotate(
                    priority=Case(
                        When(facts__reasons__contains=["missing"], then=Value(0)),
                        When(facts__reasons__contains=["generated"], then=Value(1)),
                        When(
                            Q(facts__reasons__contains=["width_below_1000"])
                            | Q(facts__reasons__contains=["height_below_1200"]),
                            then=Value(2),
                        ),
                        default=Value(3),
                        output_field=IntegerField(),
                    )
                ).order_by("priority", "calibre_id", "id")[
                    (page - 1) * PAGE_SIZE : page * PAGE_SIZE
                ]
            )
            authors: dict[int, list[str]] = {}
            for book_id, name in (
                CalibreBookAuthor.objects.filter(book_id__in=[row.calibre_id for row in entries])
                .exclude(author__name__isnull=True)
                .order_by("book_id", "position")
                .values_list("book_id", "author__name")
            ):
                if name is not None:
                    authors.setdefault(book_id, []).append(name)
            isbns: dict[int, str] = {}
            for book_id, value in (
                CalibreIdentifier.objects.filter(
                    book_id__in=[row.calibre_id for row in entries], type="isbn"
                )
                .order_by("book_id", "position")
                .values_list("book_id", "value")
            ):
                isbns.setdefault(book_id, value or "")
            pending = cover_candidates.pending_selections(entries, model)
            return response(
                {
                    "counts": counts,
                    "census": cover_reviews.census_data(census),
                    "inventory": model.token,
                    "stale": census is None
                    or census.inventory_token != model.token
                    or census.state != "complete",
                    "state": state,
                    "reason": reason,
                    "page": page,
                    "page_size": PAGE_SIZE,
                    "pages": max(1, math.ceil(total / PAGE_SIZE)),
                    "total": total,
                    "entries": [
                        cover_reviews.entry_data(
                            row,
                            authors.get(row.calibre_id, []),
                            selection_pending=pending[row.pk],
                            isbn=isbns.get(row.calibre_id, ""),
                        )
                        for row in entries
                    ],
                }
            )

    return endpoint(request, action)


@require_GET
def suggestions(request):
    def action():
        params = request.GET
        if set(params) != {"entry", "inventory", "version", "sha256"} or any(
            len(params.getlist(k)) != 1 or not params[k] for k in ("inventory", "version", "sha256")
        ):
            raise ValueError
        requested = params.getlist("entry")
        if not 1 <= len(requested) <= PAGE_SIZE:
            raise ValueError
        revisions = {}
        for item in requested:
            entry_id, revision = item.split(":")
            cover_reviews.request_uuid(entry_id)
            if not revision.isascii() or not revision.isdecimal() or not 1 <= int(revision) < 2**63:
                raise ValueError
            if entry_id in revisions or str(int(revision)) != revision:
                raise ValueError
            revisions[entry_id] = int(revision)
        direct_library.check_token(params["inventory"])
        with cover_reviews.library_read_model.consistent():
            model = cover_reviews.read_model()
            rows = list(CoverReviewEntry.objects.filter(pk__in=revisions))
            if (
                model.token != params["inventory"]
                or len(rows) != len(revisions)
                or any(
                    row.library_uuid != model.library_uuid
                    or not row.present
                    or row.revision != revisions[str(row.pk)]
                    or not cover_reviews.skippable(row)
                    for row in rows
                )
            ):
                raise cover_reviews.ReviewError("conflict")
        with (
            direct_library.snapshot(params["inventory"]) as (library_db, root, inventory),
            catalogue.snapshot(
                settings.LIBRARIUM_CATALOGUE_DIR,
                params["version"],
                params["sha256"],
                settings.LIBRARIUM_CATALOGUE_FIXTURE,
                seconds=10,
            ) as (db, info),
        ):
            if inventory["library_uuid"] != model.library_uuid:
                raise cover_reviews.ReviewError("conflict")
            books = []
            for row in rows:
                identities = library_db.execute(
                    "SELECT id FROM books WHERE uuid=? LIMIT 2", [row.book_uuid]
                ).fetchall()
                if len(identities) != 1 or identities[0][0] != row.calibre_id:
                    raise cover_reviews.ReviewError("conflict")
                book = direct_library.project(
                    library_db,
                    root,
                    direct_library.record(library_db, str(row.calibre_id)),
                    inventory,
                    read_files=False,
                )
                if book["uuid"] != row.book_uuid:
                    raise cover_reviews.ReviewError("conflict")
                books.append(book)
            matches = library_matching.match_page(books, db, info, inventory)
            entries = []
            for row, match in zip(rows, matches, strict=True):
                exact = [
                    c
                    for c in match["candidates"]
                    if c["title_status"] == c["authors_status"] == "same"
                ]
                work = (
                    exact[0]["work_id"]
                    if match["status"] == "matched" and len(exact) == 1
                    else None
                )
                entries.append(
                    {
                        "id": str(row.pk),
                        "revision": row.revision,
                        "book_id": str(row.calibre_id),
                        "book_uuid": row.book_uuid,
                        "library_uuid": row.library_uuid,
                        "work_id": work,
                        "cover": catalogue_covers.metadata(db, info, work) if work else None,
                    }
                )
        # A skip, census or read-model refresh during matching invalidates the whole page.
        latest = cover_reviews.read_model()
        if (
            latest.token != model.token
            or latest.library_uuid != model.library_uuid
            or any(
                not CoverReviewEntry.objects.filter(
                    pk=row.pk, revision=row.revision, present=True
                ).exists()
                for row in rows
            )
        ):
            raise cover_reviews.ReviewError("conflict")
        return response({"inventory": inventory["token"], "snapshot": info, "entries": entries})

    return endpoint(request, action)


@require_http_methods(["GET", "POST"])
def census(request):
    def action():
        if request.method == "POST":
            body(request, set())
            row = cover_reviews.start(request.headers.get("Idempotency-Key", ""))
            return response(cover_reviews.census_data(row), 202)
        parameters(request, set())
        model = cover_reviews.read_model()
        row = (
            CoverCensus.objects.filter(library_uuid=model.library_uuid)
            .order_by("-created_at")
            .first()
        )
        return response({"census": cover_reviews.census_data(row)})

    return endpoint(request, action)


@require_POST
def cancel(request, census_id):
    def action():
        body(request, set())
        return response(cover_reviews.cancel(census_id))

    return endpoint(request, action)


@require_POST
def skip(request, entry_id):
    def action():
        value = body(request, {"revision", "skipped"})
        return response(
            cover_reviews.set_skip(
                entry_id,
                value["revision"],
                value["skipped"],
                request.headers.get("Idempotency-Key", ""),
                principal(request),
            )
        )

    return endpoint(request, action)


@require_GET
def cover(request, entry_id):
    def action():
        parameters(request, set())
        row = CoverReviewEntry.objects.filter(pk=entry_id, present=True).first()
        if row is None:
            raise cover_reviews.ReviewError("missing", 404)
        if row.facts.get("status") != "known" or not row.facts.get("media_type"):
            raise cover_reviews.ReviewError("missing", 404)
        with cover_reviews.current_entry(row) as (root, book):
            raw, metadata = direct_library.read_cover(
                root, book["path"], limit=cover_facts.MAX_BYTES
            )
        if hashlib.sha256(raw).hexdigest() != row.facts.get("sha256"):
            raise cover_reviews.ReviewError("conflict")
        reply = HttpResponse(raw, content_type=metadata["media_type"])
        reply["Content-Length"] = str(len(raw))
        reply["Cross-Origin-Resource-Policy"] = "same-origin"
        reply["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; sandbox"
        return reply

    return endpoint(request, action)
