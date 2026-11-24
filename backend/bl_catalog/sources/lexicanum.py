"""Retained pure Lexicanum parser used to verify resolver redirect evidence.

Inbox traversal, XML-file import, quarantine and file moves are not included.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, cast

from bl_catalog.isbn import extract_isbns, to_isbn13
from bl_catalog.names import normalise
from bl_catalog.record import Record
from bl_catalog.wikitext import (
    clean_wiki_value,
    find_infobox,
)

SOURCE = "lexicanum"
WIKIS = ("wh40k", "whfb", "ageofsigmar", "catalogue")
_EXTENSIONS = {".xml", ".txt", ".wiki"}

# page-title / link suffix -> Record.type. "Audio Book" is an audio drama here.
_TYPE_BY_SUFFIX = {
    "novel": "novel",
    "novella": "novella",
    "short story": "short_story",
    "audio drama": "audio_drama",
    "audio book": "audio_drama",
    "omnibus": "omnibus",
    "anthology": "anthology",
}

# category plural -> the suffix word it stands for (looked up in _TYPE_BY_SUFFIX through _type_of, so
# the type mapping lives in one place). A category "<anything> novels" names the type for any setting.
_PLURAL_BY_SUFFIX = {
    "novels": "novel",
    "novellas": "novella",
    "short stories": "short story",
    "audio dramas": "audio drama",
    "audio books": "audio book",
    "omnibuses": "omnibus",
    "omnibus": "omnibus",
    "anthologies": "anthology",
}

# Pages that list books rather than describe one; never attribute their ISBNs to a single work.
_LISTING_TITLE_RE = re.compile(r"(series|list of|portal:|category:|publications)", re.IGNORECASE)

_NOT_A_NAME = {"various", "various authors", "unknown", "n/a", "tba", "tbc", "none"}

# --- wikitext fragments -------------------------------------------------------------------------

_FOOTNOTE_RE = re.compile(r"\{\{\s*(?:Fn|Endn)\s*\|[^{}]*\}\}", re.IGNORECASE)
_PERSON_TPL_RE = re.compile(r"\{\{\s*(?:Auth|Actor)\s*\|\s*([^{}|]+?)\s*\}\}", re.IGNORECASE)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_INVISIBLE_RE = re.compile("[\u200b-\u200f\u202a-\u202e\ufeff]")
_LINK_RE = re.compile(
    r"\[\[(?!(?:File|Image|Category):)([^\]|]+?)(?:\|([^\]]*))?\]\]", re.IGNORECASE
)
_SUFFIX_RE = re.compile(r"\s*\(([^()]+)\)\s*$")
_CATEGORY_SOURCES_RE = re.compile(
    r"\[\[\s*Category:\s*Sources\s*\(([^)\]]+)\)\s*(?:\|[^\]]*)?\]\]", re.IGNORECASE
)
_REDIRECT_RE = re.compile(r"^\s*#\s*redirect\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_FIELD_RE = re.compile(r"^\|\s*([^=|]+?)\s*=(.*)$")


def _strip_markup_noise(text: str) -> str:
    """Remove footnote templates and unwrap ``{{Auth|X}}`` / ``{{Actor|X}}`` into ``[[X]]``."""
    text = _FOOTNOTE_RE.sub("", text)
    return _PERSON_TPL_RE.sub(lambda m: f"[[{m.group(1)}]]", text)


def _clean(raw: str) -> str:
    """One cleaned line of text from a raw value (templates and markup gone)."""
    out = clean_wiki_value(_INVISIBLE_RE.sub("", _BR_RE.sub(" ", raw)))
    while "{{" in out:  # templates nested inside templates survive one pass
        stripped = clean_wiki_value(out)
        if stripped == out:
            out = out.replace("{{", "").replace("}}", "")
            break
        out = stripped
    return out.strip()


def _lines(raw: str) -> list[str]:
    """Split a raw value on ``<br>`` and newlines, dropping empty pieces."""
    parts = [piece for chunk in _BR_RE.split(raw) for piece in chunk.splitlines()]
    return [p.strip() for p in parts if p.strip()]


def _strip_suffix(title: str) -> tuple[str, str | None]:
    """``"Horus Rising (Novel)"`` -> (``"Horus Rising"``, ``"Novel"``)."""
    m = _SUFFIX_RE.search(title)
    if not m:
        return title.strip(), None
    return title[: m.start()].strip(), m.group(1).strip()


_INVERTED_ARTICLE_RE = re.compile(r"^(.+?),\s*(The|A|An)$")


def _uninvert_article(title: str) -> str:
    """``"Enemy Within, The"`` (a sorted page title) -> ``"The Enemy Within"``."""
    m = _INVERTED_ARTICLE_RE.match(title)
    return f"{m.group(2)} {m.group(1)}" if m else title


def _type_of(suffix: str | None) -> str | None:
    """Record.type of a title suffix. A qualified suffix such as ``Danie Ware Short Story`` counts:
    it is the known type with words in front. The one parser for book pages, series and redirects."""
    if not suffix:
        return None
    low = " ".join(suffix.lower().split())
    if "graphic novel" in low:  # a comic, not a book we catalogue ("Graphic Novel" ends in "novel")
        return None
    if low in _TYPE_BY_SUFFIX:
        return _TYPE_BY_SUFFIX[low]
    return next((t for k, t in _TYPE_BY_SUFFIX.items() if low.endswith(f" {k}")), None)


_CATEGORY_RE = re.compile(r"\[\[\s*Category\s*:\s*([^\]|]+?)\s*(?:\|[^\]]*)?\]\]", re.IGNORECASE)


def _is_graphic_novel(title: str) -> bool:
    """A title whose suffix says graphic novel; such pages are never book pages."""
    suffix = _strip_suffix(title)[1]
    return bool(suffix) and "graphic novel" in cast(str, suffix).lower()


def _category_type(text: str, *, ignore_audio_books: bool = False) -> str | None:
    """Record.type named by the page's categories (``Age of Sigmar novels`` -> novel), for a page
    whose title has no type suffix. A category ending in a type plural gives that type for any
    setting prefix; a graphic-novel category gives none. Categories that disagree (an audio book
    also filed under novels) name no type rather than guess. Catalogue can ignore Audio Books
    here because that category also describes audiobook editions of a fiction work."""
    kinds: set[str] = set()
    for name in _CATEGORY_RE.findall(text):
        low = " ".join(name.lower().split())
        if "graphic novel" in low:
            continue
        if ignore_audio_books and (low == "audio books" or low.endswith(" audio books")):
            continue  # Catalogue can file a novel and its audiobook edition together.
        for plural, suffix in _PLURAL_BY_SUFFIX.items():
            if low == plural or low.endswith(f" {plural}"):
                if kind := _type_of(suffix):
                    kinds.add(kind)
                break
    return next(iter(kinds)) if len(kinds) == 1 else None


_OMNIBUS_RE = re.compile(r"\bomnibus\b", re.IGNORECASE)
_SERIES_WORD_RE = re.compile(r"\bseries$", re.IGNORECASE)
_CATEGORY_SERIES_RE = re.compile(r"(.*?)\s*(?:\([^()]*\bseries\)|\bseries)$", re.IGNORECASE)


def _fallback_type(title: str, text: str) -> str | None:
    """The type of a page whose title suffix gives none. The word "Omnibus" in the title wins
    (Lexicanum files 40K omnibuses under "Anthologies"); otherwise the categories decide.
    A series-titled page ("Necromunda (Short Story Series)") is not a book and gets none."""
    suffix = _strip_suffix(title)[1]
    if suffix and _SERIES_WORD_RE.search(suffix.strip()):
        return None
    if _OMNIBUS_RE.search(title):
        return "omnibus"
    return _category_type(text)


def _series_key(name: str) -> str:
    """Series name for comparing: normalised, without a ``(Novel Series)`` / `` series`` tail, so
    an infobox ``Ciaphas Cain (Novel Series)`` and the category's ``Ciaphas Cain`` are one."""
    m = _CATEGORY_SERIES_RE.fullmatch(" ".join(name.split()))
    return normalise(m.group(1) if m and m.group(1).strip() else name)


def _category_series(text: str) -> list[str]:
    """Series named by the page's categories: ``Ciaphas Cain (Novel Series)`` and
    ``Legends of the Age of Sigmar series`` both name a series (the part before the suffix)."""
    out: list[str] = []
    type_words = set(_TYPE_BY_SUFFIX) | set(_PLURAL_BY_SUFFIX)
    for cat in _CATEGORY_RE.findall(text):
        m = _CATEGORY_SERIES_RE.fullmatch(" ".join(cat.split()))
        name = m.group(1).strip() if m else ""
        # a bare "Series" or "Novel series" category names no series
        if name and name.lower() not in type_words and name not in out:
            out.append(name)
    return out


def _names(raw: str) -> list[str]:
    """Person names from a field value: links, bold or plain text, split on , ; & and "and"."""
    raw = _INVISIBLE_RE.sub("", _BR_RE.sub(", ", raw))
    text = _LINK_RE.sub(lambda m: m.group(2) or m.group(1), raw)
    text = re.sub(r"\([^)]*\)", "", text.replace("'''", "").replace("''", ""))
    out: list[str] = []
    for c in re.split(r"\s*(?:,|;|&|\band\b)\s*", clean_wiki_value(text)):
        name = c.strip(" .")
        if name and name.lower() not in _NOT_A_NAME and name not in out:
            out.append(name)
    return out


def _first_int(raw: str) -> int | None:
    m = re.search(r"\d[\d,]*", _clean(raw))
    return int(m.group().replace(",", "")) if m else None


def _runtime_minutes(raw: str) -> int | None:
    """``5 hours 23 minutes`` -> 323; ``75 minutes`` -> 75; a bare number is minutes."""
    text = _clean(raw).lower()
    hours = re.search(r"(\d+)\s*(?:h\b|hrs?\b|hours?\b)", text)
    mins = re.search(r"(\d+)\s*(?:m\b|mins?\b|minutes?\b)", text)
    if hours or mins:
        total = (int(hours.group(1)) * 60 if hours else 0) + (int(mins.group(1)) if mins else 0)
        return total or None
    n = _first_int(text)
    return n or None


_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
            ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
            ("september", "sept", "sep"), ("october", "oct"), ("november", "nov"),
            ("december", "dec"),
        ],
        1,
    )
    for m in names
}  # fmt: skip
_MONTH = r"([A-Za-z]{3,9})\.?"


def _release_date(raw: str) -> str | None:
    """The release date at the source's own precision, else None (never the raw text).

    A full date gives ``YYYY-MM-DD``, a month and year ``YYYY-MM``, a bare year ``YYYY``. A day or
    month the source did not give is never invented. A value with a year but no usable month
    ("circa 2007") falls back to the year.
    """
    text = re.sub(r"\([^)]*\)", "", _clean(raw)).strip(" .")
    if not text:
        return None
    text = re.sub(r"\s*,\s*", ", ", text)

    def month(name: str) -> int | None:
        return _MONTHS.get(name.lower())

    try:
        if m := re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th)? {_MONTH},? (\d{{4}})", text):
            if mo := month(m[2]):
                return date(int(m[3]), mo, int(m[1])).isoformat()
        elif m := re.fullmatch(rf"{_MONTH} (\d{{1,2}})(?:st|nd|rd|th)?,? (\d{{4}})", text):
            if mo := month(m[1]):
                return date(int(m[3]), mo, int(m[2])).isoformat()
        elif m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text):
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        elif m := re.fullmatch(r"(\d{4})-(\d{2})", text):
            return date(int(m[1]), int(m[2]), 1).isoformat()[:7]
        elif m := re.fullmatch(rf"{_MONTH},? (\d{{4}})", text):
            if mo := month(m[1]):
                return date(int(m[2]), mo, 1).isoformat()[:7]
        elif m := re.fullmatch(r"\d{4}", text):
            return text
    except ValueError:
        pass  # an impossible date: fall back to whatever year it names
    y = _YEAR_RE.search(text)
    return y.group(0) if y else None


_CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR"}
_CURRENCY_CODES = ("GBP", "USD", "EUR", "CAD", "AUD", "NZD")
_AMOUNT = r"\d+(?:[.,]\d{1,2})?"
_CUR = rf"(?:[£$€]|\b(?:{'|'.join(_CURRENCY_CODES)})\b)"
_PRICE_RE = re.compile(
    rf"(?P<c1>{_CUR})\s*(?P<a1>{_AMOUNT})|(?P<a2>{_AMOUNT})\s*(?P<c2>{_CUR})", re.IGNORECASE
)


def _price(raw: str) -> tuple[float, str] | None:
    """``(amount, ISO currency)`` from a Price value, only when a currency symbol or code comes
    with the amount (``£8.99``, ``8,99 €``, ``GBP 7.99``). A bare number, text or an empty value
    gives None: a price without a currency is not evidence of anything."""
    m = _PRICE_RE.search(html.unescape(_clean(raw)))
    if not m:
        return None
    cur = (m["c1"] or m["c2"]).upper()
    cur = _CURRENCY_SYMBOLS.get(cur, cur)
    amount = float((m["a1"] or m["a2"]).replace(",", "."))
    return (amount, cur) if amount > 0 else None


def _format_of(text: str) -> str | None:
    """Map an edition description (``Hardback (2022)``, ``2012 softcover``) to a format."""
    t = text.lower()
    if "limited" in t:
        return "limited"
    if "special" in t:
        return "special"
    if re.search(r"hard\s?(?:back|cover|bound)", t):
        return "hardcover"
    if re.search(r"soft\s?(?:back|cover)|paperback|trade paper", t):
        return "paperback"
    if re.search(r"e-?book|kindle", t):
        return "ebook"
    if "audio" in t:
        return "audiobook"
    return None


def _cover_artist(caption: str | None, explicit: str | None) -> str | None:
    """A person named by an ``Artist`` field or a caption ("Cover art by X", "Cover: X").

    A bare "Cover art" caption names nobody and sets nothing.
    """
    for raw in (explicit, caption):
        if not raw:
            continue
        text = _clean(raw)
        m = re.search(r"\b(?:art|artwork|illustration|version)\s+by\s+(.+)$", text, re.IGNORECASE)
        if not m:
            m = re.search(r"\bcover(?:\s+art(?:ist)?)?\s*:\s*(.+)$", text, re.IGNORECASE)
        name = m.group(1) if m else (text if raw is explicit else "")
        name = re.sub(r"\([^)]*\)", "", name).strip(" .;:,")
        if name and name[0].isupper() and len(name.split()) <= 6:
            return name
    return None


# --- infobox ------------------------------------------------------------------------------------


def _norm_key(key: str) -> str:
    """An infobox field name in one spelling: lower case, no ``(s)``, ``_`` and runs of spaces as
    one space. ``Author(s)`` -> ``author``, ``Cover_Artist`` -> ``cover artist``."""
    key = re.sub(r"\(\s*s\s*\)\s*$", "", key.lower().strip())
    return " ".join(key.replace("_", " ").split())


def _raw_fields(box: str) -> dict[str, str]:
    """Infobox ``|Key = value`` fields with their raw values, joining continuation lines
    (an ``Editions`` value is often spread over several lines). Keys are normalised
    (``_norm_key``); when two spellings of one field both appear, the filled one wins."""
    fields: dict[str, str] = {}
    seen_filled: set[str] = set()
    key: str | None = None
    body = box[2:-2] if box.endswith("}}") else box[2:]
    lines = body.splitlines()
    if lines:  # the opening line is "{{Book", possibly followed by the first field
        lines[0] = re.sub(r"^\{?\{?\s*\w+", "", lines[0].strip())
    for line in lines:
        m = _FIELD_RE.match(line.strip()) if line.lstrip().startswith("|") else None
        if m:
            key = _norm_key(m.group(1))
            if key in seen_filled and not m.group(2).strip():
                key = None  # an empty alias of a field that already has a value
                continue
            fields[key] = m.group(2).strip()
        elif key is not None:
            fields[key] += "\n" + line
        if key is not None and fields[key].strip():
            seen_filled.add(key)
    return fields


_ISBN10_RE = re.compile(r"(?<![\d-])\d(?:[-\s]?\d){8}[-\s]?[\dXx](?!\d)")


def _isbn10s(text: str) -> dict[str, str]:
    """ISBN-13 -> the ISBN-10 spelling printed in ``text``, for each ISBN-10 it contains."""
    out: dict[str, str] = {}
    for m in _ISBN10_RE.finditer(text):
        digits = re.sub(r"[-\s]", "", m.group()).upper()
        code = to_isbn13(digits)
        if code and len(digits) == 10:
            out.setdefault(code, digits)
    return out


@dataclass
class _Edition:
    isbn13: str
    isbn10: str | None = None
    format: str | None = None
    year: str | None = None


def _editions(fields: dict[str, str]) -> tuple[list[_Edition], set[str]]:
    """Every ISBN in the ``ISBN`` and ``Editions`` fields, each with the format and year its
    own line (or the heading line just above it) gives, plus every format the page mentions."""
    found: dict[str, _Edition] = {}
    formats: set[str] = set()
    for key in ("isbn", "isbn-10", "isbn-13", "editions"):
        raw = fields.get(key, "")
        pending_fmt: str | None = None
        pending_year: str | None = None
        for line in _lines(raw):
            text = _clean(line)
            fmt = _format_of(text)
            year = (_YEAR_RE.search(text) or [None])[0]
            if fmt:
                formats.add(fmt)
            codes = extract_isbns(text)
            tens = _isbn10s(text)
            if not codes:
                if fmt or year:  # a header line for the ISBN line(s) below it
                    pending_fmt, pending_year = fmt, year
                continue
            for code in dict.fromkeys(codes):
                ed = found.setdefault(code, _Edition(isbn13=code))
                ed.format = ed.format or fmt or pending_fmt
                ed.year = ed.year or year or pending_year
                ed.isbn10 = ed.isbn10 or tens.get(code)
            pending_fmt = pending_year = None
    return list(found.values()), formats


# --- sections -----------------------------------------------------------------------------------

_SECTION_END_L2 = re.compile(r"(?<!=)==(?!=)[^=\n]{1,120}?==(?!=)")
_SECTION_END_ANY = re.compile(r"={2,}[^=\n]{1,120}?={2,}")


# footnote-style templates a heading may carry after its name: ``==Cover Description{{Fn|1}}==``
_HEADING_NOTES = r"(?:\{\{[^{}\n]*\}\}[ \t]*)*"

# the synopsis comes from the first of these headings the page has (matched case-insensitively)
_SYNOPSIS_HEADINGS = ("Cover description", "Synopsis", "Plot Summary", "Description")


def _section(text: str, names: tuple[str, ...], *, subsections: bool) -> str | None:
    """Body of the first ``==name==`` section, wherever the heading sits on its line (Lexicanum
    exports often collapse line breaks, giving ``text ==Contents== * [[..]]``). It runs to the next
    heading: any level, or with ``subsections`` only the next level-2 heading."""
    for name in names:
        m = re.search(
            rf"(?<!=)==(?!=)[ \t]*{re.escape(name)}[ \t]*{_HEADING_NOTES}[ \t]*==(?!=)",
            text,
            re.IGNORECASE,
        )
        if not m:
            continue
        rest = text[m.end() :]
        end = (_SECTION_END_L2 if subsections else _SECTION_END_ANY).search(rest)
        return rest[: end.start()] if end else rest
    return None


_HEADING_RE = re.compile(r"^(={3,})\s*(.+?)\s*\1\s*$")
_BY_RE = re.compile(r"^\W*(?:written\s+)?by\s+(.+?)[.\s]*$", re.IGNORECASE)
_MAIN_RE = re.compile(r"\{\{\s*Main\s*\|\s*([^{}|]+?)\s*(?:\|[^{}]*)?\}\}", re.IGNORECASE)
_PAREN_TYPE_RE = re.compile(
    r"\(\s*(novel|novella|short story|audio drama|audio book|omnibus|anthology)\s*\)", re.IGNORECASE
)


def _entry(
    link: tuple[str, str] | None, text: str, authors_raw: str | None, main: str | None = None
) -> dict | None:
    """One contents entry from a link (target, display) or heading text."""
    if link:
        target, display = link
        base, suffix = _strip_suffix(target.strip())
        title = clean_wiki_value(display).strip() if display and display.strip() else base
        kind = _type_of(suffix)
    else:
        title, kind = _clean(text), None
    if main and not kind:
        kind = _type_of(_strip_suffix(main)[1])
    if not kind:
        m = _PAREN_TYPE_RE.search(text)
        kind = _type_of(m.group(1)) if m else None
    if not title:
        return None
    return {
        "title": title,
        "authors": _by_authors(authors_raw) if authors_raw else [],
        "type": kind,
        "position": 0,
    }


def _by_authors(raw: str) -> list[str]:
    """The people of a "by ..." tail: its links when it has any ("by [[A]] and [[B]],
    Warhammer 40,000:" is A and B), else the plain names before any ":" note."""
    links = _LINK_RE.findall(raw)
    if links:
        names = (clean_wiki_value(display or target).strip() for target, display in links)
        return list(dict.fromkeys(n for n in names if n and n.lower() not in _NOT_A_NAME))
    return _names(raw.split(":", 1)[0])


# "by [[" opens an author credit; a "by" inside a title ("Death by Misadventure") is not one
_BY_LINK_RE = re.compile(r"(?:^|\s)by\s+(?=\[\[)", re.IGNORECASE)


def _parse_contents(text: str) -> list[dict]:
    """Entries of the ``==Contents==`` section: one per ``*`` bullet with a link, and one per
    ``===heading===`` block (its ``by X`` line gives the authors)."""
    body: Any = _section(text, ("Contents", "Contents and Editions"), subsections=True)
    if body is None:
        return []
    # put bullets and sub-headings that were collapsed onto one line back on their own lines
    body = re.sub(r"(?<=\S)[ \t]+(?=\*(?!\*)\s*(?:\[\[|\"|''))", "\n", body)
    body = re.sub(r"(?<=\S)[ \t]+(?====+[^=\n]+===)", "\n", body)
    entries: list[dict] = []
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        h = _HEADING_RE.match(line)
        if h:
            heading = h.group(2)
            body = []
            i += 1
            while (
                i < len(lines)
                and not _HEADING_RE.match(lines[i].strip())
                and not lines[i].lstrip().startswith("*")
            ):
                body.append(lines[i].strip())
                i += 1
            authors = next(
                (bm.group(1) for b in body if (bm := _BY_RE.match(_BR_RE.sub("", b)))), None
            )
            main = next((mm.group(1) for b in body if (mm := _MAIN_RE.search(b))), None)
            link = _LINK_RE.search(heading)
            grouping = i < len(lines) and lines[i].lstrip().startswith("*")
            if grouping and not link and not any(body):
                continue  # "===Warhammer 40,000===" over a list of bullets: a group, not a story
            e = _entry(
                cast(tuple[str, str], link.groups()) if link else None, heading, authors, main
            )
            if e:
                entries.append(e)
            continue
        if re.match(r"^\*(?!\*)", line):
            rest = line.lstrip("*").strip()
            link = _LINK_RE.search(rest)
            by_link = _BY_LINK_RE.search(rest)
            if by_link and (link is None or link.start() >= by_link.start()):
                # "* '''Stitches''' by [[Nick Kyme]]": the only link is the author's; the title
                # is the text before "by", never the author link
                e = _entry(None, rest[: by_link.start()], rest[by_link.end() :])
                if e:
                    entries.append(e)
            elif link:
                after = rest[link.end() :]
                by = re.search(r"\bby\s+(.+)$", after, re.IGNORECASE)
                e = _entry(cast(tuple[str, str], link.groups()), after, by.group(1) if by else None)
                if e:
                    entries.append(e)
        i += 1
    for pos, e in enumerate(entries, 1):
        e["position"] = pos
    return entries


# --- series pages -------------------------------------------------------------------------------

_SERIES_TITLE_RE = re.compile(r"\s*\([^()]*\bSeries\)\s*$", re.IGNORECASE)
_SERIES_CATEGORY_RE = re.compile(
    r"\[\[\s*Category\s*:\s*Series of books\s*(?:\|[^\]]*)?\]\]", re.IGNORECASE
)
_ANY_HEADING_RE = re.compile(r"(?<!=)(={2,6})(?!=)[ \t]*([^=\n]{1,120}?)[ \t]*\1(?!=)")
_SKIPPED_HEADINGS = {"see also", "sources", "related articles", "related"}
_GALLERY_RE = re.compile(r"<gallery\b[^>]*>(.*?)</gallery>", re.IGNORECASE | re.DOTALL)
_REDIRECT_TARGET_RE = re.compile(r"^\s*#\s*redirect\s*:?\s*\[\[([^\]|]+)", re.IGNORECASE)
_COLLAPSED_BULLET_RE = re.compile(r"(?<=\S)[ \t]+(?=\*(?!\*)[ \t]*(?:\[\[|\'\'))")


def _is_series_page(title: str, text: str) -> bool:
    if title.strip().casefold().startswith("list of"):
        return False  # a list filed among the series ("List of Media set during ..."), not one
    return bool(_SERIES_TITLE_RE.search(title) and "Series" in title) or bool(
        _SERIES_CATEGORY_RE.search(text)
    )


def _without_skipped_sections(text: str) -> str:
    """``text`` minus the See also / Sources / Related sections (each runs to the next heading of
    the same or a higher level; headings may sit mid-line in collapsed exports)."""
    pieces: list[str] = []
    skipping: int | None = None  # level of the skipped heading
    last = 0
    for m in _ANY_HEADING_RE.finditer(text):
        if skipping is None:
            pieces.append(text[last : m.start()])
        level = len(m.group(1))
        if skipping is not None and level <= skipping:
            skipping = None
        if skipping is None and " ".join(m.group(2).lower().split()) in _SKIPPED_HEADINGS:
            skipping = level
        last = m.end()
    if skipping is None:
        pieces.append(text[last:])
    return "\n".join(pieces)


def _norm_target(raw: str) -> str:
    """A link or redirect target as a page title: anchor cut, ``_`` as space, no leading ``:``."""
    return " ".join(raw.split("#", 1)[0].replace("_", " ").lstrip(":").split())


def _book_targets(chunk: str) -> list[str]:
    """Targets of the links in ``chunk`` whose page title ends in a book-type suffix, in order."""
    out = []
    for target, _label in _LINK_RE.findall(chunk):
        target = _norm_target(target)
        if target and _strip_suffix(target)[0] and _type_of(_strip_suffix(target)[1]):
            out.append(target)
    return out


def parse_series_page(wiki: str, title: str, text: str | None) -> list[Record]:
    """Membership-only Records from a Lexicanum "Series of books" page.

    One Record per distinct book-type link found in a bullet item (its first one) or a
    ``<gallery>`` line, outside the See also / Sources / Related sections. ``work_ids`` points at the work's own page so the
    resolver joins the two. No positions: these lists are unofficial and in publication order.
    """
    if not text or not text.strip():
        return []
    text = _without_skipped_sections(_strip_markup_noise(text))
    # gallery lines get a marker: every book link on them counts (a collapsed gallery is one long
    # line), whereas a bullet item names its own book first and may mention others after it
    text = _GALLERY_RE.sub(
        lambda m: (
            "\n" + "\n".join(f"\x01{ln}" for ln in m.group(1).splitlines() if ln.strip()) + "\n"
        ),
        text,
    )
    targets: list[str] = []
    for line in _COLLAPSED_BULLET_RE.sub("\n", text).splitlines():
        if line.startswith("\x01"):
            targets += _book_targets(line)
        elif line.lstrip().startswith("*"):
            targets += _book_targets(line)[:1]

    series_name = _SERIES_TITLE_RE.sub("", title).strip() or title.strip()
    recs: list[Record] = []
    for target in dict.fromkeys(targets):
        base, suffix = _strip_suffix(target)
        kind = _type_of(suffix)
        recs.append(
            Record(
                source=SOURCE,
                native_id=f"{wiki}:{title}#{target}",
                raw={"wiki": wiki, "series_page": title, "target": target},
                title=base,
                type=kind,
                series=[(series_name, None)],
                work_ids={SOURCE: f"{wiki}:{target}"},
            )
        )
    return recs


def _parse_redirect(wiki: str, title: str, text: str) -> list[Record]:
    """An alias Record for a redirect from one book-type title to another; otherwise ``[]``.

    Both ends must be book titles of the same type (Audio Book and Audio Drama are one type). A
    story redirecting to the anthology or omnibus that contains it names a different work, so
    it is not an alias. Nothing is emitted either when the two titles differ only in case.
    """
    m = _REDIRECT_TARGET_RE.match(text)
    if not m:
        return []
    target = _norm_target(m.group(1))
    alias, alias_suffix = _strip_suffix(title)
    base, suffix = _strip_suffix(target)
    kind = _type_of(alias_suffix)
    if not (alias and base and kind and kind == _type_of(suffix)):
        return []
    if alias.casefold() == base.casefold():
        return []
    return [
        Record(
            source=SOURCE,
            native_id=f"{wiki}:{title}",
            raw={"wiki": wiki, "redirect": title, "target": target},
            aliases=[alias],
            work_ids={SOURCE: f"{wiki}:{target}"},
        )
    ]


# --- page -> records ----------------------------------------------------------------------------


def parse_page(wiki: str, title: str, text: str | None) -> list[Record]:
    """Turn one Lexicanum page into Records (``[]`` for pages with nothing to say)."""
    if not text or not text.strip():
        return []
    if _REDIRECT_RE.match(text):
        return _parse_redirect(wiki, title, text)
    if _is_graphic_novel(title):
        return []  # a comic: not a book for the catalog, with or without an infobox
    if not _type_of(_strip_suffix(title)[1]) and any(
        "graphic novel" in " ".join(c.lower().split()) for c in _CATEGORY_RE.findall(text)
    ):
        return []  # filed under graphic novels and nothing in the title says otherwise
    text = _strip_markup_noise(text)

    box = find_infobox(text)
    kind = re.match(r"\{\{\s*(Book|Short)\b", box, re.IGNORECASE) if box else None
    if not kind:
        box = None  # an {{Infobox book}} from another wiki's layout: its fields are not ours
    fields = _raw_fields(box) if box else {}

    if not box and _is_series_page(title, text):
        return parse_series_page(wiki, title, text)

    work_type = (
        _type_of(_strip_suffix(title)[1])
        or ("short_story" if kind and kind.group(1).lower() == "short" else None)
        or _fallback_type(title, text)
        or (_category_type(text, ignore_audio_books=True) if wiki == "catalogue" else None)
    )
    # Catalogue covers gaming and hobby products too. A Book infobox or ISBN alone
    # does not distinguish its fiction from a rulebook, so require a known fiction type.
    if wiki == "catalogue" and box and work_type is None:
        return []

    if not box:
        # No {{Book}}/{{Short}} infobox: only an individual book page that prints ISBNs is usable.
        # Series, magazine, character and planet pages are skipped: their ISBNs belong to others.
        if _LISTING_TITLE_RE.search(title) or _type_of(_strip_suffix(title)[1]) is None:
            return []
        body_isbns = extract_isbns(text)
        if not body_isbns:
            return []
        editions = [_Edition(isbn13=i) for i in body_isbns]
        formats: set[str] = set()
    else:
        editions, formats = _editions(fields)
        if field_fmt := _format_of(_clean(fields.get("format", ""))):
            formats.add(field_fmt)  # the infobox's own Format field

    page_id = f"{wiki}:{title}"
    base_title, suffix = _strip_suffix(title)
    # The page title names the book; editors copy infoboxes and leave a stale Name (The
    # Bleeding Chalice's says "Soul Drinker"), so a Name that differs is only an alias.
    name = _clean(fields.get("name", ""))
    # a parenthetical that is no type and carries a number ("(2017/18)") is part of the title
    shown = base_title if not suffix or _type_of(suffix) or not re.search(r"\d", suffix) else title
    record_title = _uninvert_article(shown.strip()) or name
    aliases = [name] if name and normalise(name) != normalise(record_title) else []

    authors = [(n, "author") for n in _names(fields.get("author", ""))]
    authors += [(n, "editor") for n in _names(fields.get("editor", ""))]
    narrators = list(
        dict.fromkeys(_names(fields.get("performer", "")) + _names(fields.get("performed by", "")))
    )
    series = [
        (clean_wiki_value(d or t).strip(), None)
        for t, d in _LINK_RE.findall(fields.get("series", ""))
    ]
    series = [s for s in series if s[0]]
    if not series and (s := _clean(fields.get("series", ""))):
        series = [(s, None)]
    have = {_series_key(n) for n, _ in series}
    for name in _category_series(text):  # "[[Category:Ciaphas Cain (Novel Series)]]"
        if _series_key(name) not in have:
            have.add(_series_key(name))
            series.append((name, None))
    contained_in = [
        clean_wiki_value(d or _strip_suffix(t)[0]).strip()
        for t, d in _LINK_RE.findall(fields.get("collected in", ""))
    ]
    factions = [m.strip() for m in _CATEGORY_SOURCES_RE.findall(text)]
    synopsis_body = _section(text, _SYNOPSIS_HEADINGS, subsections=False)
    synopsis = (clean_wiki_value(synopsis_body)[:4000].strip() or None) if synopsis_body else None
    release_date = _release_date(fields.get("released", ""))
    price = _price(fields.get("price", ""))
    page_format = next(iter(formats)) if len(formats) == 1 else None
    print_formats = formats - {"audiobook"}
    runtime = _runtime_minutes(fields.get("length", ""))
    has_audio = bool(narrators or runtime)
    cover_artist = _cover_artist(
        fields.get("image caption"), fields.get("cover artist") or fields.get("artist")
    )
    raw: dict[str, Any] = {
        "wiki": wiki,
        "page": title,
        "fields": {
            k: v
            for k, v in ((k, _clean(v)) for k, v in fields.items())
            if v and (k != "price" or price)  # an unparseable price is dropped, never stored raw
        },
        "isbns": [e.isbn13 for e in editions],
    }
    # Preserve File/Image markup for the cover downloader; generic text cleaning removes it.
    if fields.get("image"):
        raw["fields"]["image"] = fields["image"].strip()

    contents = _parse_contents(text)

    def build(ed: _Edition | None, fmt: str | None = None) -> Record:
        fmt = fmt or (ed.format if ed else None) or page_format
        rel = release_date
        if ed and ed.year and release_date and ed.year != release_date[:4]:
            rel = None  # this edition is not the one the page's release date describes
        audio = fmt == "audiobook"  # narrators and runtime describe the audio edition only
        return Record(
            source=SOURCE,
            native_id=page_id,
            raw=raw,
            title=record_title,
            aliases=list(aliases),
            authors=list(authors),
            type=work_type,
            series=list(series),
            synopsis=synopsis,
            tags=[("faction", f) for f in factions],
            contents=[dict(c) for c in contents],
            contained_in=list(contained_in),
            work_ids={SOURCE: page_id},
            lexicanum_cover=fields.get("image", "").strip(),
            format=fmt,
            isbn13=ed.isbn13 if ed else None,
            isbn10=ed.isbn10 if ed else None,
            publisher=_clean(fields.get("publisher", "")) or None,
            release_date=rel,
            pages=_first_int(fields.get("pages", "")),
            runtime_minutes=runtime if audio else None,
            narrators=list(narrators) if audio else [],
            cover_artist=cover_artist,
            # one price is only evidence for one edition: a page with several has no way to say which
            price=price[0] if price and len(editions) <= 1 else None,
            price_currency=price[1] if price and len(editions) <= 1 else None,
        )

    def audio_edition() -> Record:
        """The audio edition when it has no ISBN of its own: narrators and runtime, no print data."""
        return replace(
            build(None, "audiobook"),
            pages=None,
            cover_artist=None,
            release_date=None,
            price=None,
            price_currency=None,
        )

    if editions:
        recs = [build(e) for e in editions]
        if has_audio and not any(r.format == "audiobook" for r in recs):
            recs.append(audio_edition())
    elif work_type == "audio_drama" or (has_audio and not print_formats):
        recs = [build(None, "audiobook")]  # the page is about the audio edition
    else:
        only_print = next(iter(print_formats)) if len(print_formats) == 1 else None
        recs = [build(None, only_print if has_audio else None)]
        if has_audio:
            recs.append(audio_edition())
    if len(recs) > 1:  # keep (source, native_id) unique per edition
        for r in recs:
            if r.isbn13:
                r.native_id = f"{page_id}#{r.isbn13}"
            elif r.format == "audiobook":
                r.native_id = f"{page_id}#audiobook"
    return recs


# --- XML / file reading -------------------------------------------------------------------------
