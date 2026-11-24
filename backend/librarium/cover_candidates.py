"""Admit local catalogue art and retain exact choices; this module has no writer.

Reuses native identity matching, digest-bound catalogue reads and the isolated
cover-facts decoder. Stored derivatives retain their original and pipeline evidence.
"""

import hashlib
import json
import re
import sqlite3
import uuid
from collections import OrderedDict
from threading import Lock
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.db import connection, transaction

from librarium import (
    catalogue,
    catalogue_covers,
    cover_facts,
    cover_reviews,
    direct_library,
    library_matching,
    library_read_model,
    package_comparison,
)
from librarium import cover_source_rules as rules
from librarium.models import CoverReviewEntry, PreparedCover

POLICY = "librarium.cover-choice.v1"
LOCK = cover_reviews.LOCK + 2
_ADMISSION: OrderedDict[tuple, dict] = OrderedDict()
_ADMISSION_LOCK = Lock()
ADMISSION_LIMIT = 256


class ChoiceError(cover_reviews.ReviewError):
    def __init__(self, message, code="choice_changed", status=409):
        Exception.__init__(self, message)
        self.code = code
        self.status = status


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def latest(entry):
    return PreparedCover.objects.filter(entry=entry).order_by("-created_at", "-id").first()


CANONICAL_FIELDS = ("sha256", "width", "height", "media_type", "selectable")


def same_canonical_bytes(a, b):
    """Web records are one image when their canonical bytes and verdict agree."""
    return a.get("method") == b.get("method") == "web_original" and all(
        a.get(key) == b.get(key) for key in CANONICAL_FIELDS
    )


def selection_data(saved, binding, candidates):
    if saved is None:
        return None
    reason = ""
    candidate_id = saved.candidate["id"]
    if saved.candidate.get("method") == "web_original":
        # Admission strips source metadata; selection is bound to the canonical image bytes.
        # The exact saved record is shown for its image when it can be; only then its bytes.
        equivalent = next(
            (c for c in candidates if c["id"] == saved.candidate["id"]), None
        ) or next((c for c in candidates if same_canonical_bytes(c, saved.candidate)), None)
        if equivalent is not None:
            candidate_id = equivalent["id"]
    if saved.binding != binding:
        reason = "The book identity or current cover changed. Choose a cover again."
    elif not any(
        c["id"] == candidate_id
        and c["selectable"]
        and bool(c.get("catalogue_suggestion")) == bool(saved.candidate.get("catalogue_suggestion"))
        and all(c[key] == saved.candidate[key] for key in ("width", "height", "media_type"))
        for c in candidates
    ):
        reason = "The catalogue artwork or its original relationship changed. Choose a cover again."
    return {
        "id": str(saved.pk),
        "candidate_id": candidate_id,
        "status": "stale" if reason else "awaiting_approval",
        "reason": reason,
    }


def known_placeholder(source):
    # Content-addressed derivatives inherit the original URL's exclusion.
    filename = unquote(urlsplit(source).path).rsplit("/", 1)[-1].casefold()
    key = re.sub(r"[^a-z0-9]", "", filename.rsplit(".", 1)[0])
    return key in {
        "nocover",
        "nocoveravailable",
        "coverunavailable",
        "noimage",
        "noimageavailable",
        "imageunavailable",
        "unknown",
        "placeholder",
    }


def placeholder_digest(db, sha256):
    # A relabelled URL cannot erase a known placeholder association for these bytes.
    if not db.execute(
        "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='cover_asset'"
    ).fetchone():
        return False
    columns = {row["name"] for row in db.execute("PRAGMA table_info(cover_asset)")}
    if not {"source_url", "sha256"} <= columns:
        return True
    rows = db.execute(
        "SELECT substr(source_url,1,4097) FROM cover_asset WHERE sha256=? LIMIT 65", (sha256,)
    ).fetchall()
    return len(rows) > 64 or any(
        not isinstance(row[0], str) or len(row[0]) > 4096 or known_placeholder(row[0])
        for row in rows
    )


def admitted(art):
    # Re-read and hash bytes on every use, even when their pixel facts are cached.
    raw = catalogue_covers.read(art)
    key = (art["sha256"], POLICY, cover_facts.POLICY)
    with _ADMISSION_LOCK:
        facts = _ADMISSION.get(key)
        if facts is not None:
            _ADMISSION.move_to_end(key)
    if facts is None:
        facts = cover_facts.inspect_cover(raw)
        if facts["status"] == "unresolved" and facts.get("error") == "inspection_failed":
            raise ChoiceError(
                "We couldn't check the catalogue right now. Refresh the choices or retry your selection.",
                "inspection_unavailable",
                503,
            )
        if facts["status"] == "known":
            with _ADMISSION_LOCK:
                _ADMISSION[key] = facts
                _ADMISSION.move_to_end(key)
                while len(_ADMISSION) > ADMISSION_LIMIT:
                    _ADMISSION.popitem(last=False)
    if (
        facts["status"] != "known"
        or facts["sha256"] != art["sha256"]
        or facts["media_type"] != art["media_type"]
        or (facts["width"], facts["height"]) != (art["width"], art["height"])
        or facts["placeholder"]
        or facts["blank"]
    ):
        raise ChoiceError("Catalogue artwork could not be admitted.")


def binding_for(row, book):
    return {
        "policy": POLICY,
        "library_uuid": row.library_uuid,
        "book_uuid": row.book_uuid,
        "current_cover_sha256": row.facts.get("sha256") or None,
        "current_cover_status": row.facts.get("status"),
        "target": digest({key: book[key] for key in ("uuid", "title", "authors", "identifiers")}),
    }


def matched_work_titles(row, params):
    """The canonical title and recorded aliases of the one catalogue work this book exactly
    matches (the match the picker's catalogue choices use, author included), else [].

    Evidence only: nothing here selects or writes. A stale token, unavailable or empty snapshot,
    an ambiguous match or no match all give no titles, never an error.
    """
    try:
        with direct_library.snapshot(params["inventory"]) as (library_db, root, inventory):
            book = direct_library.project(
                library_db,
                root,
                direct_library.record(library_db, str(row.calibre_id)),
                inventory,
                read_files=False,
            )
        if book["uuid"] != row.book_uuid:
            return []
        with catalogue.snapshot(
            settings.LIBRARIUM_CATALOGUE_DIR,
            params["version"],
            params["sha256"],
            settings.LIBRARIUM_CATALOGUE_FIXTURE,
            seconds=15,
        ) as (db, info):
            work = eligible_work(library_matching.match(book, db, info, inventory))
            if work is None:
                return []
            found = db.execute(
                "SELECT title FROM work WHERE id=? UNION ALL "
                "SELECT title FROM work_alias WHERE work_id=? LIMIT 257",
                (work, work),
            ).fetchall()
    except (
        ChoiceError,
        catalogue.CatalogueError,
        direct_library.DirectLibraryError,
        sqlite3.Error,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ):
        return []
    return [t for (t,) in found if isinstance(t, str) and 0 < len(t) <= 512][:256]


def eligible_work(match):
    exact = [c for c in match["candidates"] if c["title_status"] == c["authors_status"] == "same"]
    return exact[0]["work_id"] if match["status"] == "matched" and len(exact) == 1 else None


def catalogue_suggestions(db, book, match):
    # Suggestions never override conflicting identifiers or ambiguous author ownership.
    if match["status"] == "ambiguous" or any(
        item["status"] not in {"unknown", "unsupported"} for item in match["identifiers"]
    ):
        return []
    title, authors, _ = library_matching.checked_book(book)
    count = db.execute(
        "SELECT count(*) FROM (SELECT id FROM work UNION ALL SELECT work_id FROM work_alias LIMIT 100001)"
    ).fetchone()[0]
    if count > 100000:
        raise catalogue.CatalogueError(
            "Catalogue suggestion search exceeds its comparison limit", 422
        )
    db.create_function(
        "cover_similarity", 1, lambda value: rules.similarity(title, value), deterministic=True
    )
    rows = db.execute(
        "SELECT work_id,max(score) AS score FROM ("
        "SELECT id AS work_id,cover_similarity(substr(title,1,513)) AS score FROM work "
        "UNION ALL SELECT work_id,cover_similarity(substr(title,1,513)) FROM work_alias"
        ") GROUP BY work_id HAVING max(score)>=0.6 ORDER BY score DESC,work_id LIMIT 16"
    ).fetchall()
    found = {}
    for row in rows:
        work = package_comparison.selected_work(db, row["work_id"])
        author_score = max(
            (
                max((rules.similarity(a, b["name"]) for b in work["authors"]), default=0)
                for a in authors
            ),
            default=0,
        )
        if author_score < 0.7:
            continue
        found[work["work_id"]] = {
            **work,
            "title_status": "suggestion",
            "authors_status": "suggestion",
            "confidence": round(0.8 * row["score"] + 0.2 * author_score, 3),
            "relationship": "similar_metadata",
        }
    if db.execute(
        "SELECT 1 FROM sqlite_schema WHERE name='work_contains' AND type='table'"
    ).fetchone():
        for child in list(found.values()):
            for row in db.execute(
                "SELECT parent_id FROM work_contains WHERE child_id=? ORDER BY parent_id LIMIT 5",
                (child["work_id"],),
            ).fetchall()[:4]:
                parent = package_comparison.selected_work(db, row[0])
                found.setdefault(
                    row[0],
                    {
                        **parent,
                        "title_status": "different",
                        "authors_status": "suggestion",
                        "confidence": child["confidence"],
                        "relationship": "contained_in",
                        "contained_title": child["title"],
                    },
                )
    return sorted(found.values(), key=lambda w: (-w["confidence"], w["work_id"]))[:4]


def work_choices(db, info, match_work, eligible, *, inspect=True):
    work = match_work["work_id"]
    original = catalogue_covers.metadata(db, info, work)
    if original is None:
        return [], "Stored artwork is unavailable."
    try:
        source_row = db.execute(
            "SELECT substr(source_url,1,4097) FROM work_cover WHERE work_id=?", (work,)
        ).fetchone()
        if source_row is None:
            return [], "The recorded artwork source is unavailable."
        source = source_row[0]
        if (
            not isinstance(source, str)
            or len(source) > 4096
            or known_placeholder(source)
            or placeholder_digest(db, original["sha256"])
        ):
            return [], "The catalogue original is a known placeholder."
        if eligible and inspect:
            admitted(original)
    except ChoiceError as error:
        if error.status == 503:
            raise
        return [], "The catalogue original could not be verified."
    except catalogue.CatalogueError as error:
        if error.status == 503:
            raise ChoiceError(
                "We couldn't check the catalogue right now. Refresh the choices.",
                "inspection_unavailable",
                503,
            ) from None
        return [], "The catalogue original could not be verified."
    except ValueError:
        return [], "The catalogue original could not be verified."
    variants = [(original, "Original", "original", "")]
    enhanced = catalogue_covers.metadata(db, info, work, upscaled=True)
    if enhanced:
        try:
            row = db.execute(
                "SELECT substr(pipeline,1,257) FROM cover_derivative WHERE original_sha256=? AND sha256=?",
                (original["sha256"], enhanced["sha256"]),
            ).fetchone()
            if row and isinstance(row[0], str) and 0 < len(row[0]) <= 256:
                if eligible and inspect:
                    admitted(enhanced)
                variants.insert(0, (enhanced, "Enhanced", "stored_derivative", row[0]))
        except (ChoiceError, catalogue.CatalogueError) as error:
            if error.status == 503:
                raise ChoiceError(
                    "We couldn't check the catalogue right now. Refresh the choices or retry your selection.",
                    "inspection_unavailable",
                    503,
                ) from None
        except sqlite3.OperationalError:
            pass
    out = []
    for art, label, method, pipeline in variants:
        identity = {
            "policy": POLICY,
            "work_id": work,
            "sha256": art["sha256"],
            "original_sha256": original["sha256"],
            "method": method,
            "pipeline": pipeline,
            "source": source,
        }
        candidate_id = str(uuid.uuid5(uuid.NAMESPACE_URL, digest(identity)))
        out.append(
            {
                **identity,
                "id": candidate_id,
                "label": label,
                "title": match_work["title"],
                "width": art["width"],
                "height": art["height"],
                "media_type": art["media_type"],
                "url": art["url"],
                "selectable": eligible,
                "meets_width_floor": art["width"] >= 1000,
                "reason": "Title and authors match one catalogue work. Confirm the edition visually."
                if eligible
                else (
                    "A different book. Not selectable."
                    if match_work["title_status"] != "same"
                    else "The book identity could not be confirmed. Not selectable."
                ),
                "source_name": urlsplit(source).hostname or "Recorded source",
                "source_url": source
                if urlsplit(source).scheme == "https"
                and urlsplit(source).hostname
                in {"wh40k.lexicanum.com", "whfb.lexicanum.com", "ageofsigmar.lexicanum.com"}
                else None,
            }
        )
    return out, ""


def suggestion_choices(db, info, work, book, *, inspect=True):
    kind = db.execute("SELECT type FROM work WHERE id=?", (work["work_id"],)).fetchone()[0]
    kind_title = (
        work["title"] + " Omnibus"
        if kind in {"anthology", "omnibus", "collection"}
        else work["title"]
    )
    allowed = work["relationship"] != "contained_in" and not rules.kind_mismatch(
        book["title"], kind_title
    )
    items, error = work_choices(db, info, work, allowed, inspect=inspect)
    for item in items:
        item.update(
            catalogue_suggestion=True,
            catalogue_confidence=work["confidence"],
            relationship=work["relationship"],
        )
        item["reason"] = (
            f"Contains {work['contained_title']}; anthology artwork, not a standalone cover. Not selectable."
            if work["relationship"] == "contained_in"
            else "Catalogue suggestion from title and author similarity; confirm the book and edition visually."
            if allowed
            else "Different publication kind. Not selectable."
        )
    return items, error


def pending_selections(rows, model):
    saved = {
        item.entry_id: item
        for item in PreparedCover.objects.filter(entry__in=rows)
        .order_by("entry_id", "-created_at", "-id")
        .distinct("entry_id")
    }
    pending = dict.fromkeys((row.pk for row in rows), False)
    if not saved:
        return pending
    books = library_read_model.entries(
        library_read_model.CalibreBook.objects.filter(
            pk__in=[row.calibre_id for row in rows if row.pk in saved]
        ),
        model.token,
    )
    by_id = {book["id"]: book for book in books}
    try:
        with catalogue.snapshot(
            settings.LIBRARIUM_CATALOGUE_DIR,
            fixture=settings.LIBRARIUM_CATALOGUE_FIXTURE,
            seconds=10,
        ) as (db, info):
            matches = library_matching.match_page(
                books, db, info, library_read_model.inventory(model)
            )
            by_match = {book["id"]: match for book, match in zip(books, matches, strict=True)}
            for row in rows:
                selected = saved.get(row.pk)
                book = by_id.get(str(row.calibre_id))
                if selected is None or book is None or book["uuid"] != row.book_uuid:
                    continue
                binding = binding_for(row, book)
                if selected.binding != binding:
                    continue
                if selected.candidate.get("method") == "web_original":
                    from librarium import cover_sources

                    pending[row.pk] = (
                        selection_data(
                            selected, binding, cover_sources.candidates(row, binding, selected)
                        )["status"]
                        == "awaiting_approval"
                    )
                    continue
                match = by_match[book["id"]]
                work = eligible_work(match)
                candidate_work = next(
                    (c for c in match["candidates"] if c["work_id"] == work), None
                )
                if selected.candidate.get("catalogue_suggestion"):
                    candidate_work = next(
                        (
                            c
                            for c in catalogue_suggestions(db, book, match)
                            if c["work_id"] == selected.candidate["work_id"]
                        ),
                        None,
                    )
                if candidate_work is None:
                    continue
                # Wall polling checks provenance/availability without starting pixel decoders.
                if selected.candidate.get("catalogue_suggestion"):
                    candidates, _ = suggestion_choices(
                        db, info, candidate_work, book, inspect=False
                    )
                else:
                    candidates, _ = work_choices(db, info, candidate_work, True, inspect=False)
                pending[row.pk] = (
                    selection_data(selected, binding, candidates)["status"] == "awaiting_approval"
                )
    except catalogue.CatalogueError, ChoiceError, ValueError:
        return dict.fromkeys(pending, False)
    return pending


def choices(entry_id, params):
    revision = params["revision"]
    if type(revision) is not int or not 1 <= revision < 2**63:
        raise ValueError
    direct_library.check_token(params["inventory"])
    row = CoverReviewEntry.objects.filter(pk=entry_id).first()
    if row is None:
        raise ChoiceError("This book is no longer in cover review.", status=404)
    if row.revision != revision:
        raise ChoiceError("This review changed. Refresh it before choosing a cover.")
    metadata = cover_reviews.metadata_signature()
    with cover_reviews.current_entry(row) as (_, record):
        path = record["path"]
    with direct_library.snapshot(params["inventory"]) as (library_db, root, inventory):
        book = direct_library.project(
            library_db,
            root,
            direct_library.record(library_db, str(row.calibre_id)),
            inventory,
            read_files=False,
        )
        if book["uuid"] != row.book_uuid or inventory["library_uuid"] != row.library_uuid:
            raise ChoiceError("The book identity changed. Refresh cover review.")
    binding = binding_for(row, book)
    # The short library snapshot is closed before matching or isolated pixel decoding.
    with catalogue.snapshot(
        settings.LIBRARIUM_CATALOGUE_DIR,
        params["version"],
        params["sha256"],
        settings.LIBRARIUM_CATALOGUE_FIXTURE,
        seconds=15,
    ) as (db, info):
        match = library_matching.match(book, db, info, inventory)
        eligible = eligible_work(match)
        candidates = []
        unavailable = []
        ordered = sorted(match["candidates"], key=lambda c: c["work_id"] != eligible)
        for work in ordered[:4]:
            items, error = work_choices(db, info, work, work["work_id"] == eligible)
            candidates.extend(items)
            if error:
                unavailable.append(error)
        if eligible is None or not candidates:
            for work in catalogue_suggestions(db, book, match):
                existing = [c for c in candidates if c["work_id"] == work["work_id"]]
                if any(c["selectable"] for c in existing):
                    continue
                items, error = suggestion_choices(db, info, work, book)
                if items:
                    candidates = [c for c in candidates if c["work_id"] != work["work_id"]]
                    candidates.extend(items[: max(0, 8 - len(candidates))])
                if error:
                    unavailable.append(error)
        catalogue_source = {
            "status": "complete" if candidates else "unavailable" if unavailable else "empty",
            "reason": ("No exact catalogue entry." if eligible is None else "")
            if candidates
            else unavailable[0]
            if unavailable
            else "No catalogue entry for this book."
            if eligible is None
            else "Stored catalogue artwork is unavailable.",
        }
    with direct_library.snapshot(params["inventory"]):
        pass
    if (
        metadata != cover_reviews.metadata_signature()
        or cover_reviews.source_signature(SimpleNamespace(path=path)) != row.source_signature
        or not CoverReviewEntry.objects.filter(pk=row.pk, revision=revision, present=True).exists()
    ):
        raise ChoiceError("The book or review changed. Refresh cover review.")
    from librarium import cover_sources

    saved = latest(row)
    candidates.extend(cover_sources.candidates(row, binding, saved))
    selectable = [c for c in candidates if c["selectable"] and not c.get("catalogue_suggestion")]
    default = next(
        (c for c in selectable if c["label"] == "Enhanced" and c["meets_width_floor"]),
        next((c for c in selectable if c["label"] == "Original"), None),
    )
    data = {
        "entry_id": str(row.pk),
        "revision": revision,
        "library_uuid": row.library_uuid,
        "book_uuid": row.book_uuid,
        "inventory": inventory["token"],
        "snapshot": info,
        "policy": POLICY,
        "web_sources_enabled": cover_sources.available(),
        "candidates": candidates,
        "default_candidate_id": default["id"] if default else None,
        "selection": selection_data(saved, binding, candidates),
        "source": catalogue_source,
    }
    return data, row, binding, metadata, path


def save(entry_id, params, key, actor):
    key = cover_reviews.request_uuid(key)
    candidate_id = str(cover_reviews.request_uuid(params["candidate_id"]))
    selection_id = params["selection_id"]
    if selection_id is not None:
        selection_id = str(cover_reviews.request_uuid(selection_id))
    previous = PreparedCover.objects.filter(request_key=key).first()
    if previous and (
        previous.entry_id != entry_id or previous.actor != actor or previous.request != params
    ):
        raise ChoiceError("This selection request was already used for another choice.")
    data, row, binding, metadata, path = choices(entry_id, params)
    if row.facts.get("status") != "known":
        raise ChoiceError(
            "The current cover could not be checked. Run Check again before selecting."
        )
    candidate = next(
        (c for c in data["candidates"] if c["id"] == candidate_id and c["selectable"]), None
    )
    if candidate is None:
        raise ChoiceError("This artwork is no longer selectable. Refresh the choices.")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK])
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [library_read_model.LOCK])
        current = CoverReviewEntry.objects.select_for_update().get(pk=entry_id)
        model = cover_reviews.read_model(lock=True)
        held = latest(row)
        previous = PreparedCover.objects.filter(request_key=key).first()
        if previous:
            if (
                previous.entry_id != entry_id
                or previous.actor != actor
                or previous.request != params
            ):
                raise ChoiceError("This selection request conflicts with another choice.")
            if held is None or previous.pk != held.pk:
                raise ChoiceError("A newer cover was selected. Refresh the choices.")
            data["selection"] = selection_data(previous, binding, data["candidates"])
            return data
        if (str(held.pk) if held else None) != selection_id or (
            current.revision != row.revision
            or not current.present
            or current.fingerprint != row.fingerprint
            or current.source_signature != row.source_signature
            or model.token != params["inventory"]
            or model.library_uuid != row.library_uuid
            or metadata != cover_reviews.metadata_signature()
            or cover_reviews.source_signature(SimpleNamespace(path=path)) != row.source_signature
        ):
            raise ChoiceError("The book, cover or selection changed. Refresh before trying again.")
        # Reopen the exact pin after decoding, before recording any selection.
        with catalogue.snapshot(
            settings.LIBRARIUM_CATALOGUE_DIR,
            params["version"],
            params["sha256"],
            settings.LIBRARIUM_CATALOGUE_FIXTURE,
        ):
            if candidate.get("method") == "web_original":
                from librarium import cover_sources

                cover_sources.verify_for_selection(candidate, entry_id, binding)
            saved = PreparedCover.objects.create(
                request_key=key,
                entry=row,
                actor=actor,
                request=params,
                binding=binding,
                candidate={k: v for k, v in candidate.items() if k != "url"},
            )
        data["selection"] = selection_data(saved, binding, data["candidates"])
    return data
