"""Native metadata matching, pinned to a library observation and catalogue bytes."""

from django.conf import settings
from django.views.decorators.http import require_GET

from librarium import catalogue, direct_library, package_comparison, package_identifiers
from librarium.direct_library_views import error_reply, invalid_reply
from librarium.validation import bounded_text
from librarium.views import response

MAX_CANDIDATES = 24
MAX_VALUES = 64
SCOPE = (
    "Recorded library metadata compared with this catalogue snapshot. A metadata match "
    "does not authenticate file contents, establish edition identity or authorize corrections. "
    "Possible matches and disagreements require review. Originals were not changed."
)


def refuse():
    return catalogue.CatalogueError("Library matching evidence exceeds the comparison limit", 422)


def checked_book(book):
    title, authors, identifiers = book.get("title"), book.get("authors"), book.get("identifiers")
    if (
        not isinstance(title, str)
        or not bounded_text(title, 512)
        or not isinstance(authors, list)
        or len(authors) > MAX_VALUES
        or any(not isinstance(name, str) or not bounded_text(name, 512) for name in authors)
        or not isinstance(identifiers, list)
        or len(identifiers) > MAX_VALUES
        or any(
            not isinstance(entry, dict)
            or any(
                not isinstance(entry.get(key), str) or not bounded_text(entry[key], 512)
                for key in ("type", "value")
            )
            for entry in identifiers
        )
    ):
        raise refuse()
    return title, authors, identifiers


def identifier_evidence(db, identifiers, *, normalize_isbn=package_identifiers._catalogue_isbn):
    entries = []
    keys = set()
    for item in identifiers:
        kind, value = item["type"].casefold(), item["value"]
        entry = {**item, "status": "unsupported"}
        if kind in {"isbn", "isbn10", "isbn13"}:
            canonical = package_identifiers.canonical_isbn(value.strip().replace(" ", ""))
            entry.update(
                canonical_isbn13=canonical,
                editions=[],
                status="invalid" if canonical is None else "unknown",
            )
            if canonical:
                keys.add(canonical)
        elif kind == "bl_catalog":
            if not bounded_text(value, 80) or not value:
                entry["status"] = "invalid"
            else:
                work_id, visited = value, set()
                for _ in range(16):
                    if work_id in visited:
                        entry["status"] = "ambiguous"
                        break
                    visited.add(work_id)
                    row = db.execute(
                        "SELECT new_id FROM id_alias WHERE old_id=?", (work_id,)
                    ).fetchone()
                    if row is None:
                        exists = db.execute("SELECT 1 FROM work WHERE id=?", (work_id,)).fetchone()
                        entry.update(
                            work_id=work_id if exists else None,
                            status="same" if exists else "unknown",
                        )
                        break
                    work_id = row[0]
                    if not isinstance(work_id, str) or not bounded_text(work_id, 80) or not work_id:
                        raise refuse()
                else:
                    entry["status"] = "ambiguous"
        entries.append(entry)
    matches = (
        package_identifiers._matches(db, sorted(keys), normalize=normalize_isbn) if keys else {}
    )
    references = 0
    for entry in entries:
        key = entry.get("canonical_isbn13")
        if key:
            editions = matches[key]
            references += len(editions)
            if references > package_identifiers.MAX_ROWS:
                raise refuse()
            entry["editions"] = editions
            owners = {edition["work_id"] for edition in editions}
            entry["status"] = (
                "unknown"
                if not editions
                else "ambiguous"
                if None in owners or len(owners) != 1 or any(e["disputed"] for e in editions)
                else "same"
            )
    return entries


def title_candidates(db, title, *, normalize=package_comparison.normalized):
    oversized = db.execute(
        "SELECT 1 FROM work WHERE typeof(title)!='text' OR length(title)>512 "
        "UNION ALL SELECT 1 FROM work_alias WHERE typeof(title)!='text' OR length(title)>512 LIMIT 1"
    ).fetchone()
    if oversized:
        raise refuse()
    db.create_function("library_match_name", 1, normalize, deterministic=True)
    key = package_comparison.normalized(title)
    if not key:
        return set()
    return {
        row[0]
        for row in db.execute(
            "SELECT id FROM work WHERE library_match_name(title)=? "
            "UNION SELECT wa.work_id FROM work_alias wa JOIN work w ON w.id=wa.work_id "
            "WHERE library_match_name(wa.title)=? LIMIT 25",
            (key, key),
        )
    }


def match(
    book,
    db,
    info,
    inventory,
    *,
    normalize=package_comparison.normalized,
    normalize_isbn=package_identifiers._catalogue_isbn,
    titles=None,
    owners=None,
):
    title, authors, identifiers = checked_book(book)
    evidence = identifier_evidence(db, identifiers, normalize_isbn=normalize_isbn)
    identifier_work_ids = {entry["work_id"] for entry in evidence if entry.get("work_id")} | {
        edition["work_id"]
        for entry in evidence
        for edition in entry.get("editions", [])
        if edition["work_id"]
    }
    titles = title_candidates(db, title, normalize=normalize) if titles is None else titles
    candidate_ids = identifier_work_ids | titles
    if len(candidate_ids) > MAX_CANDIDATES or any(
        not isinstance(value, str) or not value or not bounded_text(value, 80)
        for value in candidate_ids
    ):
        raise refuse()
    owners = (
        package_comparison.name_owners(db, authors, normalize=normalize)
        if owners is None
        else owners
    )
    candidates = []
    for work_id in sorted(candidate_ids):
        work = package_comparison.selected_work(db, work_id)
        creators = package_comparison.creator_finding(authors, work["authors"], owners, True)
        candidates.append(
            {
                **work,
                "title_status": "same" if work_id in titles else "different",
                "title_basis": "canonical"
                if package_comparison.normalized(title)
                == package_comparison.normalized(work["title"])
                else "recorded_alias"
                if work_id in titles
                else None,
                "authors_status": creators["status"],
                "author_matches": [
                    {
                        "library_name": row["epub_name"],
                        **{k: v for k, v in row.items() if k != "epub_name"},
                    }
                    for row in creators["matches"]
                ],
                "identifier_match": work_id in identifier_work_ids,
            }
        )
    matching = [row for row in candidates if row["title_status"] == row["authors_status"] == "same"]
    if (
        any(entry["status"] in {"ambiguous", "invalid"} for entry in evidence)
        or len(identifier_work_ids) > 1
        or any(row["authors_status"] == "ambiguous" for row in candidates)
        or len(matching) > 1
    ):
        status, basis = "ambiguous", "conflicting_or_ambiguous_evidence"
    elif identifier_work_ids:
        selected = next(row for row in candidates if row["identifier_match"])
        status = "matched" if selected in matching else "disagreement"
        basis = (
            "identifier_and_metadata" if status == "matched" else "identifier_metadata_disagreement"
        )
    elif len(matching) == 1:
        status, basis = "matched", "title_and_authors"
    elif candidates:
        status, basis = "disagreement", "incomplete_or_different_authors"
    else:
        status, basis = "unmatched", "no_supported_candidate"
    return {
        "schema_version": "librarium.library-match.v1",
        "policy_version": "librarium.library-match.v1",
        "inventory": inventory,
        "book": {key: book.get(key) for key in ("id", "uuid", "title", "authors")},
        "catalogue": info,
        "status": status,
        "basis": basis,
        "identifiers": evidence,
        "candidates": candidates,
        "ready": False,
        "scope": SCOPE,
    }


def match_page(books, db, info, inventory):
    """Share global title/alias and author ownership scans across one bounded page."""
    if not 1 <= len(books) <= 24:
        raise refuse()
    checked = [checked_book(book) for book in books]
    keys: dict[str, set[str]] = {package_comparison.normalized(title): set() for title, _, _ in checked}
    oversized = db.execute(
        "SELECT 1 FROM work WHERE typeof(title)!='text' OR length(title)>512 "
        "UNION ALL SELECT 1 FROM work_alias WHERE typeof(title)!='text' OR length(title)>512 LIMIT 1"
    ).fetchone()
    if oversized:
        raise refuse()
    db.create_function("library_match_name", 1, package_comparison.normalized, deterministic=True)
    placeholders = ",".join("?" for _ in keys)
    matches = db.execute(
        "SELECT id,library_match_name(title) AS spelling FROM work "
        f"WHERE library_match_name(title) IN ({placeholders}) "
        "UNION SELECT wa.work_id,library_match_name(wa.title) AS spelling "
        "FROM work_alias wa JOIN work w ON w.id=wa.work_id "
        f"WHERE library_match_name(wa.title) IN ({placeholders}) LIMIT ?",
        [*keys, *keys, 24 * MAX_CANDIDATES + 1],
    ).fetchall()
    if len(matches) > 24 * MAX_CANDIDATES:
        raise refuse()
    for work_id, spelling in matches:
        if spelling:
            keys[spelling].add(work_id)
    owners = package_comparison.name_owners(db, [name for _, names, _ in checked for name in names])
    return [
        match(
            book,
            db,
            info,
            inventory,
            titles=keys[package_comparison.normalized(title)],
            owners=owners,
        )
        for book, (title, _, _) in zip(books, checked, strict=True)
    ]


@require_GET
def match_book(request, book_id):
    required = {"inventory", "version", "sha256"}
    params = request.GET
    if set(params) != required or any(len(params.getlist(k)) != 1 or not params[k] for k in params):
        return invalid_reply()
    try:
        direct_library.check_token(params["inventory"])
        observed = direct_library.detail(book_id, params["inventory"])
        with catalogue.snapshot(
            settings.LIBRARIUM_CATALOGUE_DIR,
            params["version"],
            params["sha256"],
            settings.LIBRARIUM_CATALOGUE_FIXTURE,
        ) as (db, info):
            data = match(observed["book"], db, info, observed["inventory"])
        direct_library.detail(book_id, params["inventory"])
        return response(data)
    except ValueError:
        return invalid_reply()
    except direct_library.DirectLibraryError as error:
        return error_reply(error)
    except catalogue.CatalogueError as error:
        return response({"error": str(error)}, error.status)
