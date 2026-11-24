"""Capture pinned catalogue metadata at the web boundary and review it without the snapshot.

The worker only ever sees the immutable captured input, so it needs no catalogue mount and
cannot drift to a newer snapshot. Nothing here reads or claims anything about the library.
"""

import json
from collections import Counter

from django.conf import settings

from librarium import catalogue
from librarium.catalogue import CatalogueError

INPUT_LIMIT = 64 * 1024
VALUE_LIMIT = 160
ITEM_LIMIT = 25
SCOPE = (
    "Catalogue snapshot metadata only. "
    "Library ownership, book files and Calibre records were not checked."
)
STAGES = [
    "Bound the pinned catalogue snapshot",
    "Recorded source agreement",
    "Checked edition ISBNs",
    "Checked bibliography completeness",
]
WORK_FIELDS = ["type", "first_published"]
EDITION_FIELDS = ["format", "publisher", "release_date"]


def capture_catalogue(work_id: str, version: str, sha256: str) -> dict:
    """Return the compact review input for one work in an exactly pinned snapshot."""
    if not version or not sha256:
        raise CatalogueError("Choose a pinned catalogue version and fingerprint", 400)
    with catalogue.snapshot(
        settings.LIBRARIUM_CATALOGUE_DIR, version, sha256, settings.LIBRARIUM_CATALOGUE_FIXTURE
    ) as (db, info):
        work = catalogue.detail(db, info, work_id)
        support_count = db.execute(
            "SELECT count(*) FROM field_support WHERE entity='work' AND entity_id=?", (work_id,)
        ).fetchone()[0]
    captured = compact(work, info, support_count)
    if len(json.dumps(captured, separators=(",", ":")).encode()) > INPUT_LIMIT:
        raise CatalogueError(
            "This work's catalogue metadata exceeds the 64 KiB review limit; it was not queued",
            422,
        )
    return captured


def compact(work: dict, info: dict, support_count: int) -> dict:
    """Shape one work's detail into review input; source text is kept only as excerpts."""
    return {
        "kind": "catalogue",
        "catalogue_work_id": work["id"],
        "title": work["title"],
        "type": work["type"],
        "first_published": work["first_published"],
        "has_synopsis": bool((work["synopsis"] or "").strip()),
        "source_version": info["version"],
        "source_sha256": info["sha256"],
        "fixture": bool(info["fixture"]),
        "authors": [{"id": a["id"], "name": a["name"]} for a in work["authors"]],
        "series": [
            {"id": s["id"], "name": s["name"], "position": s["position"]} for s in work["series"]
        ],
        "editions": work["editions"],
        "edition_count": work["edition_count"],
        "editions_truncated": work["edition_count"] > len(work["editions"]),
        "support": [support_excerpt(entry) for entry in work["support"]],
        "support_count": support_count,
        "support_truncated": support_count > len(work["support"]),
    }


def text_of(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def bounded(value) -> str | None:
    text = text_of(value)
    if text is None:
        return None
    return text if len(text) <= VALUE_LIMIT else text[: VALUE_LIMIT - 1] + "…"


def cut(value) -> bool:
    text = text_of(value)
    return text is not None and len(text) > VALUE_LIMIT


def excerpt(value) -> tuple:
    """Return `value` shortened to about VALUE_LIMIT characters and whether it was cut."""
    if not isinstance(value, list):
        return (bounded(value), True) if cut(value) else (value, False)
    # Lists stay lists so a source's names are not re-escaped inside one JSON string; the
    # budget is the list's JSON text, which is what a finding later displays.
    kept: list[str] = []
    used = 2
    for item in value:
        text = text_of(item) or ""
        cost = len(json.dumps(text, ensure_ascii=False)) + bool(kept)
        if used + cost > VALUE_LIMIT:
            room = VALUE_LIMIT - used - bool(kept) - 3
            if room > 0:
                kept.append(text[:room] + "…")
            return kept, True
        kept.append(text)
        used += cost
    return kept, False


def marked(entry: dict, value) -> dict:
    # A cut value is stored as `excerpt`, never `value`, so it cannot pass as the full text.
    short, truncated = excerpt(value)
    return {**entry, ("excerpt" if truncated else "value"): short}


def shown(entry: dict) -> tuple:
    """Return the stored text and whether it is an excerpt; old inputs hold full values."""
    if "excerpt" in entry:
        return entry["excerpt"], True
    return entry["value"], cut(entry["value"])


def support_excerpt(entry: dict) -> dict:
    # Every source record is kept so disagreement counts and origins stay exact; only its
    # text is cut.
    return marked(
        {
            "field": bounded(entry["field"]),
            "agree": [bounded(origin) for origin in entry["agree"]],
            "disagree": [
                marked({"origin": bounded(d["origin"])}, d["value"]) for d in entry["disagree"]
            ],
        },
        entry["value"],
    )


def excerpted(entry: dict) -> bool:
    return shown(entry)[1] or any(shown(d)[1] for d in entry["disagree"])


def present(value) -> bool:
    return value is not None and str(value).strip() != ""


def status(problems: bool, complete: bool, checked: int) -> str:
    if problems:
        return "attention"
    if checked == 0:
        return "not_checked"
    return "pass" if complete else "partial"


def coverage(payload: dict) -> dict:
    return {
        "editions_checked": len(payload["editions"]),
        "edition_count": payload["edition_count"],
        "editions_truncated": payload["editions_truncated"],
        "support_checked": len(payload["support"]),
        "support_count": payload["support_count"],
        "support_truncated": payload["support_truncated"],
        "complete": not payload["editions_truncated"] and not payload["support_truncated"],
    }


def bound_result(payload: dict, input_fingerprint: str) -> dict:
    return {
        "kind": "catalogue",
        "read_only": True,
        "synthetic": payload["fixture"],
        "input_fingerprint": input_fingerprint,
        "catalogue_work_id": payload["catalogue_work_id"],
        "source_version": payload["source_version"],
        "source_sha256": payload["source_sha256"],
        "coverage": coverage(payload),
        "findings": [],
        "scope": SCOPE,
    }


def partial_note(checked: int, total: int, noun: str) -> str:
    return f" Only {checked} of {total} {noun} were captured; the rest were not checked."


def display(entry: dict) -> dict:
    value, truncated = shown(entry)
    return {"value": bounded(value), "value_truncated": truncated or cut(value)}


def source_finding(payload: dict) -> dict:
    support = payload["support"]
    conflicts = [entry for entry in support if entry["disagree"]]
    shortened = sum(excerpted(entry) for entry in support)
    hidden = [e for e in conflicts[:ITEM_LIMIT] if len(e["disagree"]) > ITEM_LIMIT]
    complete = not payload["support_truncated"]
    state = status(bool(conflicts), complete, len(support))
    if not support:
        detail = "No source support was recorded for this work; agreement was not checked."
    elif conflicts:
        fields = ", ".join(sorted({bounded(e["field"]) or "" for e in conflicts}))
        detail = (
            f"{len(conflicts)} of {len(support)} recorded values have a disagreeing source "
            f"({fields}). Disagreement shows the sources differ, not which one is right."
        )
        for entry in hidden[:3]:
            detail += (
                f" {bounded(entry['field'])} lists {ITEM_LIMIT} of {len(entry['disagree'])} "
                "disagreeing sources; all are counted."
            )
        if len(conflicts) > ITEM_LIMIT:
            detail += f" {ITEM_LIMIT} of {len(conflicts)} disagreeing values are listed."
    else:
        detail = f"All {len(support)} recorded values have no disagreeing source."
    if shortened:
        detail += (
            f" {shortened} recorded values are shown as excerpts of at most {VALUE_LIMIT} "
            "characters; the full source text was not copied."
        )
    if not complete:
        detail += partial_note(len(support), payload["support_count"], "source records")
    return {
        "name": "Source agreement",
        "ok": state == "pass",
        "status": state,
        "detail": detail,
        "counts": {
            "values_checked": len(support),
            "values_recorded": payload["support_count"],
            "disagreements": len(conflicts),
            "excerpted": shortened,
            "origins": len(
                {o for e in support for o in e["agree"]}
                | {d["origin"] for e in support for d in e["disagree"]}
            ),
        },
        "items": [
            {
                "field": bounded(e["field"]),
                **display(e),
                "agree": [bounded(o) for o in e["agree"][:ITEM_LIMIT]],
                "agree_count": len(e["agree"]),
                "disagree": [
                    {"origin": bounded(d["origin"]), **display(d)}
                    for d in e["disagree"][:ITEM_LIMIT]
                ],
                "disagree_count": len(e["disagree"]),
            }
            for e in conflicts[:ITEM_LIMIT]
        ],
    }


def isbn_text(value) -> str | None:
    if not present(value):
        return None
    return str(value).replace("-", "").replace(" ", "").upper()


def valid_isbn13(value: str) -> bool:
    return (
        len(value) == 13
        and value.isascii()
        and value.isdigit()
        and sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(value)) % 10 == 0
    )


def valid_isbn10(value: str) -> bool:
    if len(value) != 10 or not value.isascii():
        return False
    if not value[:9].isdigit() or not (value[9].isdigit() or value[9] == "X"):
        return False
    digits = [10 if c == "X" else int(c) for c in value]
    return sum((10 - i) * d for i, d in enumerate(digits)) % 11 == 0


def isbn_finding(payload: dict) -> dict:
    editions = payload["editions"]
    counts = Counter[str]()
    items: list[dict] = []
    owners: dict[str, dict[str, list[str]]] = {"isbn13": {}, "isbn10": {}}

    def note(edition: dict, problem: str, value: str | None) -> None:
        items.append(
            {"edition_id": bounded(edition["id"]), "problem": problem, "value": bounded(value)}
        )

    for edition in editions:
        isbn13, isbn10 = isbn_text(edition["isbn13"]), isbn_text(edition["isbn10"])
        if isbn13 is None and isbn10 is None:
            counts["no_isbn"] += 1
            continue
        good13 = good10 = False
        if isbn13 is not None:
            counts["isbn13_recorded"] += 1
            good13 = valid_isbn13(isbn13)
            counts["isbn13_valid" if good13 else "isbn13_invalid"] += 1
            if not good13:
                note(edition, "isbn13_checksum", edition["isbn13"])
            owners["isbn13"].setdefault(isbn13, []).append(edition["id"])
        if isbn10 is not None:
            counts["isbn10_recorded"] += 1
            good10 = valid_isbn10(isbn10)
            counts["isbn10_valid" if good10 else "isbn10_invalid"] += 1
            if not good10:
                note(edition, "isbn10_checksum", edition["isbn10"])
            owners["isbn10"].setdefault(isbn10, []).append(edition["id"])
        if good13 and good10 and isbn13 and isbn10:
            counts["pairs_checked"] += 1
            # Only 978 ISBN-13s have an ISBN-10 form; it shares the nine body digits.
            if not (isbn13.startswith("978") and isbn13[3:12] == isbn10[:9]):
                counts["pairs_mismatched"] += 1
                note(edition, "isbn_pair_mismatch", f"{isbn13} / {isbn10}")

    for kind, values in owners.items():
        for value, ids in values.items():
            if len(ids) > 1:
                counts[f"duplicate_{kind}"] += 1
                for edition_id in ids:
                    items.append(
                        {
                            "edition_id": bounded(edition_id),
                            "problem": f"duplicate_{kind}",
                            "value": bounded(value),
                        }
                    )

    failures = counts["isbn13_invalid"] + counts["isbn10_invalid"] + counts["pairs_mismatched"]
    checked = counts["isbn13_recorded"] + counts["isbn10_recorded"]
    complete = not payload["editions_truncated"]
    state = status(failures > 0, complete, checked)
    duplicates = counts["duplicate_isbn13"] + counts["duplicate_isbn10"]
    if checked == 0:
        detail = (
            f"None of the {len(editions)} captured editions records an ISBN; nothing was checked."
        )
    else:
        detail = (
            f"Checked {checked} recorded ISBNs on {len(editions) - counts['no_isbn']} editions: "
            f"{counts['isbn13_invalid']} ISBN-13 and {counts['isbn10_invalid']} ISBN-10 fail "
            f"their checksums; {counts['pairs_mismatched']} of {counts['pairs_checked']} "
            "ISBN-13/ISBN-10 pairs disagree."
        )
        failed = [i["value"] for i in items if i["problem"].endswith("_checksum")]
        if failed:
            detail += f" Failing: {', '.join(v for v in failed[:5] if v)}."
        if counts["no_isbn"]:
            detail += f" {counts['no_isbn']} editions record no ISBN."
    if duplicates:
        detail += (
            f" {duplicates} ISBNs are shared by more than one edition; review them, "
            "this alone does not show either record is wrong."
        )
    if not complete:
        detail += partial_note(len(editions), payload["edition_count"], "editions")
    keys = [
        "isbn13_recorded",
        "isbn13_valid",
        "isbn13_invalid",
        "isbn10_recorded",
        "isbn10_valid",
        "isbn10_invalid",
        "pairs_checked",
        "pairs_mismatched",
        "no_isbn",
        "duplicate_isbn13",
        "duplicate_isbn10",
    ]
    return {
        "name": "ISBN checks",
        "ok": state == "pass",
        "status": state,
        "detail": detail,
        "counts": {
            "editions_checked": len(editions),
            "edition_count": payload["edition_count"],
            **{key: counts[key] for key in keys},
        },
        "items": items[:ITEM_LIMIT],
    }


def bibliography_finding(payload: dict) -> dict:
    missing = [field for field in WORK_FIELDS if not present(payload[field])]
    if not payload["has_synopsis"]:
        missing.append("synopsis")
    if not payload["authors"]:
        missing.append("authors")
    if payload["edition_count"] == 0:
        missing.append("editions")
    editions = payload["editions"]
    gaps = {
        f"editions_missing_{field}": sum(not present(e[field]) for e in editions)
        for field in EDITION_FIELDS
    }
    complete = not payload["editions_truncated"]
    problems = bool(missing) or any(gaps.values())
    state = status(problems, complete, 1)
    parts = []
    if missing:
        parts.append(f"Work record lacks: {', '.join(missing)}.")
    edition_gaps = [
        f"{count} without {key.removeprefix('editions_missing_').replace('_', ' ')}"
        for key, count in gaps.items()
        if count
    ]
    if edition_gaps:
        parts.append(f"Of {len(editions)} captured editions, {'; '.join(edition_gaps)}.")
    if not parts:
        parts.append(
            "Work type, first publication, synopsis, authors and edition format, publisher "
            "and release date are all recorded."
        )
    detail = " ".join(parts)
    if not payload["series"]:
        detail += " No series membership is recorded; standalone works need none."
    if not complete:
        detail += partial_note(len(editions), payload["edition_count"], "editions")
    return {
        "name": "Bibliography completeness",
        "ok": state == "pass",
        "status": state,
        "detail": detail,
        "missing": missing,
        "counts": {
            "editions_checked": len(editions),
            "edition_count": payload["edition_count"],
            "authors": len(payload["authors"]),
            "series": len(payload["series"]),
            **gaps,
        },
    }


def advance_result(checkpoint: int, payload: dict, result: dict, input_fingerprint: str) -> dict:
    """Return the durable result after completing step `checkpoint` (1-4)."""
    if checkpoint == 1:
        return bound_result(payload, input_fingerprint)
    finding = {2: source_finding, 3: isbn_finding, 4: bibliography_finding}[checkpoint](payload)
    return {**result, "findings": [*result["findings"], finding]}
