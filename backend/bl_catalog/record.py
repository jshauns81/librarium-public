"""The Record model: one source's view of one item, flattened into claims."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import cast

from bl_catalog.isbn import strip_isbn_label, to_isbn13
from bl_catalog.names import normalise

Claim = tuple[str, str, str, str]  # (entity, field, value_json, value_norm)

_ISBN_SHAPE = re.compile(r"\d{13}|\d{9}[\dX]")


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _empty(value: object) -> bool:
    return (
        value is None
        or (isinstance(value, str) and not value.strip())
        or (isinstance(value, (list, dict, tuple)) and not value)
    )


def _num(value: float) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:g}" if value == int(value) else repr(value)
    return str(value)


def _ident(value: str) -> str:
    return value.strip().upper()


def _token(value: str) -> str:
    return value.strip().lower()


def _plain(value: str) -> str:
    return value.strip()


# scalar field -> (entity, normaliser). Text uses names.normalise; identifiers and enum-like
# values use a canonical form that keeps their punctuation.
_SCALARS: dict[str, tuple[str, object]] = {
    "title": ("work", normalise),
    "type": ("work", _token),
    "setting": ("work", normalise),
    "synopsis": ("work", normalise),
    "word_count": ("work", _num),
    "first_published": ("work", _plain),
    "format": ("edition", _token),
    "asin": ("edition", _ident),
    "audible_asin": ("edition", _ident),
    "publisher": ("edition", normalise),
    "imprint": ("edition", normalise),
    "release_date": ("edition", _plain),
    "region": ("edition", _token),
    "pages": ("edition", _num),
    "runtime_minutes": ("edition", _num),
    "cover_artist": ("edition", normalise),
    "cover_url": ("edition", _plain),
    "price": ("edition", lambda v: f"{float(v):.2f}"),
    "price_currency": ("edition", _ident),
    "in_print": ("edition", lambda v: "1" if v else "0"),
}


@dataclass
class Record:
    source: str
    native_id: str
    cache_ref: str | None = None
    raw: dict = field(default_factory=dict)

    # work fields
    title: str | None = None
    authors: list[tuple[str, str]] = field(default_factory=list)  # (name, role)
    type: str | None = None
    setting: str | None = None
    series: list[tuple[str, float | None]] = field(default_factory=list)  # (name, position)
    synopsis: str | None = None
    word_count: int | None = None
    first_published: str | None = None
    aliases: list[str] = field(default_factory=list)
    tags: list[tuple[str, str]] = field(default_factory=list)  # (kind, value)
    contents: list[dict] = field(default_factory=list)  # {title, authors, type, position}
    contained_in: list[str] = field(default_factory=list)
    work_ids: dict[str, str] = field(default_factory=dict)
    # None: no image observation; "": the Lexicanum infobox explicitly has no cover.
    lexicanum_cover: str | None = None

    # edition fields
    format: str | None = None
    isbn13: str | None = None
    isbn10: str | None = None
    asin: str | None = None
    audible_asin: str | None = None
    publisher: str | None = None
    imprint: str | None = None
    release_date: str | None = None
    region: str | None = None
    pages: int | None = None
    runtime_minutes: int | None = None
    narrators: list[str] = field(default_factory=list)
    cover_artist: str | None = None
    cover_url: str | None = None
    price: float | None = None
    price_currency: str | None = None
    in_print: bool | None = None
    edition_ids: dict[str, str] = field(default_factory=dict)

    def to_claims(self) -> list[Claim]:
        """One claim per non-empty scalar and per element of each list field.

        Returns (entity, field, value_json, value_norm) sorted by (entity, field, value_norm,
        value_json). Only exact duplicates collapse, so distinct structured elements that share
        a name (same author in two roles, same series at two positions) are all kept and the
        result (and content_hash) does not depend on input order. Series positions are
        stored as floats so 1 and 1.0 are the same claim. Structured values (author with role,
        series with position, tag with kind, contents entry) keep the whole structure in
        value_json and use the normalised name/title as value_norm. An author claim is
        ``[name, role, credit]``: ``credit`` is the name's 0-based place among the record's
        credits in that role, so the credited order of co-authors survives the sort.
        """
        out: set[tuple[str, str, str, str]] = set()  # (entity, field, value_norm, value_json)

        def put(entity: str, fld: str, value: object, norm: str) -> None:
            if norm:
                out.add((entity, fld, norm, _dumps(value)))

        for fld, (entity, norm_fn) in _SCALARS.items():
            value = getattr(self, fld)
            if not _empty(value):
                put(entity, fld, _canon(fld, value), norm_fn(value))  # type: ignore[operator]

        # Track an image-only revision (including removal) independently of raw parser data.
        if self.lexicanum_cover is not None:
            filename = self.lexicanum_cover.strip()
            put("work", "lexicanum_cover", filename, filename or "-")

        for raw in (self.isbn13, self.isbn10):
            if _empty(raw):
                continue
            canonical = to_isbn13(cast(str, raw))
            if canonical:
                put("edition", "isbn13", canonical, canonical)
                continue
            digits = re.sub(r"[-\s]", "", strip_isbn_label(cast(str, raw))).upper()
            if _ISBN_SHAPE.fullmatch(digits):
                put("edition", "isbn_invalid", digits, digits)

        credits: dict[str, list[str]] = {}  # role -> names in credited order, first mention
        for name, role in self.authors:
            names = credits.setdefault(role, [])
            if name not in names:
                names.append(name)
        for role, names in credits.items():
            for index, name in enumerate(names):
                put("work", "author", [name, role, index], normalise(name))
        for name, position in self.series:
            pos = None if position is None else float(position)
            put("work", "series", [name, pos], normalise(name))
        for alias in self.aliases:
            put("work", "alias", alias, normalise(alias))
        for kind, value in self.tags:
            put("work", "tag", [kind, value], normalise(value))
        for item in self.contents:
            put("work", "contents", _canon_contents(item), normalise(item.get("title", "")))
        for title in self.contained_in:
            put("work", "contained_in", title, normalise(title))
        for kind, value in self.work_ids.items():
            put("work", "work_id", [kind, value], f"{_token(kind)}:{value.strip()}")
        for narrator in self.narrators:
            put("edition", "narrator", narrator, normalise(narrator))
        for kind, value in self.edition_ids.items():
            put("edition", "edition_id", [kind, value], f"{_token(kind)}:{value.strip()}")

        return [(e, f, v, n) for e, f, n, v in sorted(out)]

    def content_hash(self) -> str:
        return hash_claims(self.to_claims())


def _canon(fld: str, value: object) -> object:
    """The value as stored in value_json: identifiers are canonicalised, the rest kept as given."""
    if fld in ("asin", "audible_asin", "price_currency") and isinstance(value, str):
        return _ident(value)
    return value


def _canon_contents(item: dict) -> dict:
    """A contents entry with a numeric position stored as float (so 1 and 1.0 agree)."""
    out = dict(item)
    pos = out.get("position")
    if isinstance(pos, (int, float)) and not isinstance(pos, bool):
        out["position"] = float(pos)
    return out


def hash_claims(claims: list[Claim]) -> str:
    return hashlib.sha256(json.dumps(claims, sort_keys=True).encode()).hexdigest()
