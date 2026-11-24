"""Field voting (spec 5.3 steps 4-6 and 8) and disputed identifiers (spec 5.3.6).

Agreement is counted per origin group, never per source: sources that copy one upstream (ISBNdb,
Google and Hardcover all repeat the trade feeds) count once. Groups and priorities come from
``sources.toml`` through ``load_sources()``; a source missing there is its own group with
priority ``DEFAULT_PRIORITY``.

Values are grouped by ``value_norm``, except where spellings of one value differ: titles and
person names are grouped into near-equal buckets (``titles.key_agreement``,
``titles.same_person``), anchored on the best-supported spelling rather than chained.

Everything here is a pure function of the claims: no tables are written (the rebuild does that),
and claim order never changes a result. The spec 5.4 flags are defined once, by the API
(``api/views._flags``), from what the rebuild writes.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date
from typing import Any, cast

from bl_catalog.config import SourceInfo
from bl_catalog.names import normalise, placeholder_person
from bl_catalog.resolve.people import display_name
from bl_catalog.resolve.titles import (
    context_words,
    fold_possessive,
    key_agreement,
    same_person,
    strip_edition_decoration,
    title_key,
    undecorated,
)
from bl_catalog.resolve.works import WorkCluster

DEFAULT_PRIORITY = 9  # priority of a source missing from sources.toml (as "the rest" there)
DATE_FIELDS = frozenset({"release_date", "first_published"})
# Multi-valued fields: every value with at least one origin group is kept (spec 5.3.5).
MULTI_FIELDS = frozenset({"author", "series", "alias", "tag", "narrator"})
# People: credits (author claims, by role) and the edition narrator field vote together, by role.
PEOPLE_FIELDS = frozenset({"author", "narrator"})
# Claims that are not voted here: identifiers become work_ident/edition_ident rows, contents
# become work_contains rows, and an invalid ISBN is evidence only.
UNVOTED_FIELDS = frozenset(
    {
        "work_id",
        "edition_id",
        "contents",
        "contained_in",
        "isbn_invalid",
        "lexicanum_cover",
    }
)
# Edition claims that belong to the work: narrators are credited on the work (work_author).
WORK_FIELDS_FROM_EDITIONS = frozenset({"narrator"})
# Claim fields that attach an edition identifier, and the edition_ident kind they give.
IDENT_FIELDS = {"isbn13": "isbn13", "asin": "asin", "audible_asin": "audible_asin"}

SHORT_STORY_BELOW = 17_500  # words (spec 5.3.8)
NOVELLA_BELOW = 50_000
WORDS_PER_PAGE = 250

_ROLE_ORDER = {"author": 0, "editor": 1, "narrator": 2, "cover_artist": 3}
_DATE = re.compile(r"\d{4}(?:-\d{2}(?:-\d{2})?)?")
# Generic series decorations only: "(Novel Series)", "(Book Series)", "(Audio Series)",
# "(Series)", "(Space Marine Battles Novel Series)". A specific disambiguator such as
# "(Warped Galaxies series)" names a sub-series and stays.
_BARE_SERIES = re.compile(
    r"\s+(?:novel|book|audio(?:\s+drama)?|short\s+story|novella)?\s*series$", re.IGNORECASE
)
_SERIES_DECORATION = re.compile(
    r"\s*\((?:[^()]*\bnovel|book|audio(?:\s+drama)?|short\s+story|novella)?\s*series\)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ClaimRow:
    """One stored claim with the source that made it. ``value`` is the decoded ``value`` JSON
    (structured claims keep their extras: an author is ``[name, role, credit]``, a series
    ``[name, position]``, a tag ``[kind, value]``); ``value_norm`` is as stored."""

    record_id: int
    source: str
    entity: str
    field: str
    value: Any
    value_norm: str

    @classmethod
    def from_claim(cls, record_id: int, source: str, claim: tuple[str, str, str, str]) -> ClaimRow:
        """From a ``Record.to_claims()`` tuple ``(entity, field, value_json, value_norm)``."""
        entity, fld, value, norm = claim
        return cls(record_id, source, entity, fld, json.loads(value), norm)


@dataclass
class Vote:
    """A resolved value and its support.

    ``agree`` lists the origin groups behind ``value``; ``disagree`` holds
    ``{"origin", "value"}`` for every value outside the winner, so a group split between the
    winner and another value appears in both. ``field`` is the field_support field (an author's
    role for people: ``author``, ``editor``, ``narrator``...), ``norm`` the winning normalised
    value, and ``extra`` the structured parts: ``role`` and ``spellings`` (people: every
    spelling the sources gave this person), ``kind`` (tags) and ``position`` (series: a nested
    ``Vote`` or None).
    """

    value: Any
    score: float
    agree: list[str]
    disagree: list[dict]
    field: str = ""
    norm: str = ""
    extra: dict = dc_field(default_factory=dict)

    def support_row(self) -> dict:
        """The ``field_support`` columns for this value (entity and entity_id are the caller's).
        For a person ``field`` is the role and ``value`` the display name: the rebuild keeps
        it as the canonical author name or one of that person's aliases."""
        return {
            "field": self.field,
            "value": _text(self.value),
            "score": self.score,
            "agree_json": json.dumps(self.agree, ensure_ascii=False),
            "disagree_json": json.dumps(self.disagree, ensure_ascii=False),
        }


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# --- loading -------------------------------------------------------------------------------


def load_claims(
    conn: sqlite3.Connection, record_ids: Iterable[int] | None = None
) -> dict[int, list[ClaimRow]]:
    """``{record_id: [ClaimRow, ...]}`` (claims in stored order), in one pass over the claim
    table. Call it once for the whole database (``record_ids=None``) and index into the result
    per work; never once per work. ``record_ids`` keeps only those records."""
    wanted = None if record_ids is None else set(record_ids)
    out: dict[int, list[ClaimRow]] = {}
    if wanted is not None and not wanted:
        return out
    for rid, source, entity, fld, value, norm in conn.execute(
        "SELECT c.record_id, r.source, c.entity, c.field, c.value, c.value_norm"
        " FROM claim c JOIN source_record r ON r.id = c.record_id ORDER BY c.id"
    ):
        if wanted is None or rid in wanted:
            row = ClaimRow(rid, source, entity, fld, json.loads(value), norm)
            out.setdefault(rid, []).append(row)
    return out


# --- ranking and buckets -------------------------------------------------------------------


def _source(name: str, sources: Mapping[str, SourceInfo]) -> tuple[str, int]:
    """(origin group, priority) of a source."""
    info = sources.get(name)
    return (info.origin_group, info.priority) if info else (name, DEFAULT_PRIORITY)


@dataclass
class _Option:
    """The claims for one normalised value."""

    norm: str
    groups: set[str]
    priority: int  # the lowest priority among the sources backing it
    claims: list[ClaimRow]

    @property
    def rank(self) -> tuple:
        return (-len(self.groups), self.priority, self.norm)


@dataclass
class _Bucket:
    """Options that are one value spelled differently; ``anchor`` is the option it formed on."""

    anchor: _Option
    options: list[_Option]

    @property
    def groups(self) -> set[str]:
        return set().union(*(o.groups for o in self.options))

    @property
    def rank(self) -> tuple:
        return (-len(self.groups), min(o.priority for o in self.options), self.anchor.norm)

    @property
    def best(self) -> _Option:
        return min(self.options, key=lambda o: o.rank)

    @property
    def claims(self) -> list[ClaimRow]:
        return [c for o in self.options for c in o.claims]


def _rank(items: Iterable[tuple[str, ClaimRow]], sources) -> list[_Option]:
    """Group ``(norm, claim)`` pairs by norm, best first: most origin groups, then the lowest
    source priority, then the smallest norm (so the order is total and claim order is
    irrelevant)."""
    options: dict[str, _Option] = {}
    for norm, claim in items:
        group, priority = _source(claim.source, sources)
        opt = options.setdefault(norm, _Option(norm, set(), priority, []))
        opt.groups.add(group)
        opt.priority = min(opt.priority, priority)
        opt.claims.append(claim)
    return sorted(options.values(), key=lambda o: o.rank)


Agree = Callable[[_Option, _Option], float]
Apart = Callable[[_Option, _Option], bool]


def _buckets(
    options: list[_Option], agree: Agree | None = None, apart: Apart | None = None
) -> list[_Bucket]:
    """Group ranked options into buckets of near-equal values, best bucket first.

    Without ``agree`` every option is its own bucket. Otherwise, pass 1 picks anchors in rank
    order: an option that agrees with no earlier anchor starts a bucket. Pass 2 puts each other
    option in the bucket of the anchor it agrees with best (the earlier anchor on a tie), unless
    it must stay ``apart`` from one of that bucket's members; with no such bucket it starts its
    own. Anchoring, not chaining: an option that agrees with two anchors
    that disagree with each other cannot join them into one value.
    """
    if agree is None:
        return [_Bucket(o, [o]) for o in options]

    def fits(a: _Option, b: _Option) -> float:
        return 0.0 if apart is not None and apart(a, b) else agree(a, b)

    buckets: list[_Bucket] = []
    for opt in options:
        if not any(fits(b.anchor, opt) for b in buckets):
            buckets.append(_Bucket(opt, [opt]))
    anchors = {id(b.anchor) for b in buckets}
    for opt in options:
        if id(opt) in anchors:
            continue
        scored = sorted(range(len(buckets)), key=lambda i: (-fits(buckets[i].anchor, opt), i))
        for i in scored:
            bucket = buckets[i]
            if fits(bucket.anchor, opt) and not any(
                apart is not None and apart(m, opt) for m in bucket.options
            ):
                bucket.options.append(opt)
                break
        else:
            buckets.append(_Bucket(opt, [opt]))
    return sorted(buckets, key=lambda b: b.rank)


def _shown(claims: list[ClaimRow], sources, shown: Callable[[ClaimRow], Any]) -> Any:
    """The value to display for claims of one option: the highest-priority source's (then by
    source name, then by value), never the first one stored."""
    best = min(
        claims,
        key=lambda c: (
            _source(c.source, sources)[1],
            c.source,
            json.dumps(shown(c), sort_keys=True, ensure_ascii=False),
        ),
    )
    return shown(best)


def _score(agree: set[str], total: set[str]) -> float:
    return round(len(agree) / len(total), 2)


def _dissent(options: Iterable[_Option], sources, shown) -> list[dict]:
    """``{"origin", "value"}`` for each (group, value) among ``options`` (the values that lost).
    A group that also backs the winner is listed too: its own sources disagree."""
    rows = []
    for opt in options:
        by_group: dict[str, list[ClaimRow]] = defaultdict(list)
        for claim in opt.claims:
            by_group[_source(claim.source, sources)[0]].append(claim)
        for group, claims in by_group.items():
            rows.append((group, opt.norm, _shown(claims, sources, shown)))
    return [{"origin": g, "value": v} for g, _, v in sorted(rows, key=lambda r: r[:2])]


def _scalar_vote(
    claims: list[ClaimRow],
    sources,
    fld: str,
    norm: Callable[[ClaimRow], str] = lambda c: c.value_norm,
    shown: Callable[[ClaimRow], Any] = lambda c: c.value,
    agree: Agree | None = None,
    display: Callable[[_Bucket], Any] | None = None,
) -> Vote:
    options = _rank(((norm(c), c) for c in claims), sources)
    buckets = _buckets(options, agree)
    win = buckets[0]
    total = set().union(*(o.groups for o in options))
    return Vote(
        value=display(win) if display else _shown(win.best.claims, sources, shown),
        score=_score(win.groups, total),
        agree=sorted(win.groups),
        disagree=_dissent([o for b in buckets[1:] for o in b.options], sources, shown),
        field=fld,
        norm=win.anchor.norm,
    )


# --- scalar fields -------------------------------------------------------------------------


def vote(
    claims: Iterable[ClaimRow], sources: Mapping[str, SourceInfo], context: Iterable[str] = ()
) -> Vote | None:
    """Resolve one single-valued field from its claims (all for the same field).

    Claims are grouped by ``value_norm`` and counted by distinct origin group. The winner has
    the most groups; a tie goes to the lowest source priority among its sources, then to the
    smallest ``value_norm``. ``score = winner groups / groups with any value``, to 2 places.
    Titles are grouped into near-equal buckets (``_title_vote``; ``context`` holds the work's
    series and author names, which may pad a title) and dates are voted by precision
    (``_vote_date``). No claims, no vote: ``None``.
    """
    claims = list(claims)
    if not claims:
        return None
    fld = _one_field(claims)
    if fld == "title":
        return _title_vote(claims, sources, context)
    if fld in DATE_FIELDS:
        return _vote_date(claims, sources, fld)
    return _scalar_vote(claims, sources, fld)


def _one_field(claims: list[ClaimRow]) -> str:
    found = {c.field for c in claims}
    if len(found) != 1:
        raise ValueError(f"claims for several fields: {sorted(found)}")
    return found.pop()


def _title_vote(claims: list[ClaimRow], sources, context: Iterable[str]) -> Vote:
    """Titles agree when ``key_agreement`` reaches 0.9: decoration ("(Unabridged)", "(The
    Horus Heresy Book 1)") and possessives don't split a title, the work's own series and author
    words may pad it, and a collection title never joins a single work's. The value shown is
    the best-supported spelling that carries no decoration."""
    words = context_words(context)

    def agree(a: _Option, b: _Option) -> float:
        return key_agreement(a.norm, b.norm, words)

    def plain(c: ClaimRow) -> bool:
        return undecorated(c.value) == c.value.strip()

    def display(bucket: _Bucket) -> str:
        clean = [o for o in bucket.options if any(plain(c) for c in o.claims)]
        if clean:
            best = min(clean, key=lambda o: o.rank)
            return _shown([c for c in best.claims if plain(c)], sources, lambda c: c.value)
        return strip_edition_decoration(_shown(bucket.best.claims, sources, lambda c: c.value))

    return _scalar_vote(
        claims, sources, "title", norm=lambda c: title_key(c.value), agree=agree, display=display
    )


def _valid_date(text: str) -> bool:
    """YYYY, YYYY-MM or YYYY-MM-DD naming a real month and day ("2006-13-45" is not a date)."""
    if not _DATE.fullmatch(text):
        return False
    try:
        date(
            int(text[:4]),
            int(text[5:7]) if len(text) >= 7 else 1,
            int(text[8:]) if len(text) == 10 else 1,
        )
    except ValueError:
        return False
    return True


def _compatible(a: str, b: str) -> bool:
    """Two dates agree when they are equal at their shared precision ("2006" ~ "2006-04-20").
    Anything that is not a valid date agrees only with the identical string."""
    if not (_valid_date(a) and _valid_date(b)):
        return a == b
    n = min(len(a), len(b))
    return a[:n] == b[:n]


def _vote_date(claims: list[ClaimRow], sources, fld: str) -> Vote:
    """Dates come at mixed precision (YYYY, YYYY-MM, YYYY-MM-DD).

    The year is voted first, by origin groups. Then the value is refined, a month and then a
    day, from the claims that agree with it and give that precision: when they all name one
    month (day), that is taken, even from a single group, so "2006" from three groups and
    "2006-04-20" from a fourth resolve to "2006-04-20" with all four agreeing. When they name
    several, the top one is taken only if two or more groups back it and more than back any
    other; otherwise the value stays at the precision every group agrees on, and the score is
    not lowered by a one-group plurality. A group agrees when any of its dates is compatible
    with the result. Invalid dates ("2006-13-45") never vote, they only dissent; when no date
    is valid the field is voted as plain text.
    """
    dated = [c for c in claims if _valid_date(c.value_norm)]
    if not dated:
        return _scalar_vote(claims, sources, fld)
    value = _rank(((c.value_norm[:4], c) for c in dated), sources)[0].norm
    for width in (7, 10):  # YYYY-MM, YYYY-MM-DD
        pool = [c for c in dated if len(c.value_norm) >= width and _compatible(c.value_norm, value)]
        if not pool:
            break
        options = _rank(((c.value_norm[:width], c) for c in pool), sources)
        top = options[0]
        if len(options) > 1 and not (
            len(top.groups) >= 2 and len(top.groups) > len(options[1].groups)
        ):
            break
        value = top.norm

    agree = {_source(c.source, sources)[0] for c in claims if _compatible(c.value_norm, value)}
    total = {_source(c.source, sources)[0] for c in claims}
    against = [c for c in claims if not _compatible(c.value_norm, value)]
    return Vote(
        value=value,
        score=_score(agree, total),
        agree=sorted(agree),
        disagree=_dissent(
            _rank(((c.value_norm, c) for c in against), sources), sources, lambda c: c.value_norm
        ),
        field=fld,
        norm=value,
    )


# --- multi-valued fields -------------------------------------------------------------------


@dataclass(frozen=True)
class _Facet:
    """How one multi-valued claim votes: within ``bucket`` (the score's denominator), under the
    field_support ``field``, by ``norm``, displayed as ``shown``; ``credit`` is its place in
    the record's credits (people only)."""

    bucket: str
    field: str
    norm: str
    shown: Any
    extra: tuple[tuple[str, str], ...] = ()
    credit: int | None = None


def strip_series_decoration(name: str) -> str:
    """'Ciaphas Cain (Novel Series)' -> 'Ciaphas Cain'. Only generic decorations go
    ("(Novel Series)", "(Book Series)", "(Audio Series)", "(Series)", "(… Novel Series)", and the
    same words bare at the end: "Horus Heresy Series", "Gaunt's Ghosts Novel Series");
    "Warhammer Adventures (Warped Galaxies series)" names a sub-series and is kept. A name that
    is nothing but the decoration is kept as given."""
    stripped = _SERIES_DECORATION.sub("", name).strip()
    stripped = _BARE_SERIES.sub("", stripped).strip()
    return stripped or name.strip()


def series_key(name: str) -> str:
    """The compared form of a series name: undecorated, possessives folded, normalised, and a
    leading "the" dropped ("Horus Heresy Series" = "The Horus Heresy")."""
    key = normalise(fold_possessive(strip_series_decoration(name)))
    rest = key.removeprefix("the ")
    return rest if rest != key and rest else key


def _facet(claim: ClaimRow) -> _Facet:
    fld, value = claim.field, claim.value
    if fld == "author":
        # inverted catalogue names ("King, William") vote with the plain form
        name, role = value[0], value[1]
        credit = value[2] if len(value) > 2 else None
        shown = display_name(name)
        return _Facet(role, role, normalise(shown), shown, (("role", role),), credit)
    if fld == "narrator":  # the edition's narrator list: a narrator credit without an order
        shown = display_name(value)
        return _Facet("narrator", "narrator", normalise(shown), shown, (("role", "narrator"),))
    if fld == "series":
        shown = strip_series_decoration(value[0])
        return _Facet("series", "series", series_key(shown), shown)
    if fld == "tag":
        kind, text = value
        return _Facet(kind, "tag", claim.value_norm, text, (("kind", kind),))
    return _Facet(fld, fld, claim.value_norm, value)


def _bucket_order(bucket: str) -> tuple[int, str]:
    return (_ROLE_ORDER.get(bucket, len(_ROLE_ORDER)), bucket)


def vote_multi(claims: Iterable[ClaimRow], sources: Mapping[str, SourceInfo]) -> list[Vote]:
    """Resolve a multi-valued field (people, series, aliases, tags): every value that at least
    one origin group gives is kept, each with its own score.

    A value's score is its groups over the groups that gave any value in its bucket: people are
    counted per role (``field`` is the role, so a work's author votes have ``field="author"``
    and the display name as ``value``), tags per kind. ``author`` and ``narrator`` claims may be
    passed together: an edition's narrator list votes with narrator-role credits.

    People are un-inverted, then spellings of one person share a vote (``same_person``: same
    surname, compatible initials, "W. King" ~ "William King"), anchored on the best-supported
    spelling, which is the value shown; two names one record credits separately are never one
    person. Co-credits keep the order of the highest-priority record that credits two or more of
    them; everything else is best first, as in ``vote``. Series names lose a generic trailing
    "(… Series)" and fold possessives before grouping, and carry ``extra["position"]``: the
    position voted among the claims for that series that give one (None when none do).

    ``disagree`` on a multi value lists each group that gave the field but not this value, with
    the values it does give. Votes come per bucket (author, editor, narrator, cover_artist,
    then others by name).
    """
    claims = list(claims)
    if not claims:
        return []
    fields = {c.field for c in claims}
    if len(fields) > 1 and not fields <= PEOPLE_FIELDS:
        raise ValueError(f"claims for several fields: {sorted(fields)}")
    buckets: dict[str, list[tuple[_Facet, ClaimRow]]] = defaultdict(list)
    for claim in claims:
        facet = _facet(claim)
        if claim.field in PEOPLE_FIELDS and placeholder_person(facet.shown):
            continue
        buckets[facet.bucket].append((facet, claim))

    votes: list[Vote] = []
    for name in sorted(buckets, key=_bucket_order):
        items = buckets[name]
        facets = {id(cl): f for f, cl in items}
        people = fields <= PEOPLE_FIELDS
        options = _rank(((f.norm, cl) for f, cl in items), sources)
        if people:
            agree = _person_agree(facets)
            groups = _buckets(
                options,
                agree,
                cast(
                    Callable[[_Option, _Option], bool],
                    lambda a, b, test=agree: _credited_apart(a, b) or not test(a, b),
                ),
            )
        else:
            groups = _buckets(options)
        total = set().union(*(o.groups for o in options))
        if name == "series":  # spellings share a vote; show the one most groups use
            shown = [_best_spelling(b.claims, sources, facets) for b in groups]
        else:
            shown = [
                _shown(
                    b.best.claims,
                    sources,
                    cast(Callable[[ClaimRow], Any], lambda c, f=facets: f[id(c)].shown),
                )
                for b in groups
            ]
        listed: dict[str, list[Any]] = defaultdict(list)  # group -> the values it gives
        for bucket, value in zip(groups, shown, strict=True):
            for group in bucket.groups:
                listed[group].append(value)
        entries = []
        for bucket, value in zip(groups, shown, strict=True):
            first = facets[id(bucket.anchor.claims[0])]
            extra: dict[str, Any] = dict(first.extra)
            if first.field == "series":
                extra["position"] = _position_vote(bucket.claims, sources)
            elif people:  # every spelling the sources gave, for the author's aliases
                extra["spellings"] = sorted({facets[id(c)].shown for c in bucket.claims})
            vote_ = Vote(
                value=value,
                score=_score(bucket.groups, total),
                agree=sorted(bucket.groups),
                disagree=[
                    {"origin": g, "value": sorted(listed[g], key=str)}
                    for g in sorted(total - bucket.groups)
                ],
                field=first.field,
                norm=bucket.anchor.norm,
                extra=extra,
            )
            entries.append((vote_, bucket.claims))
        if people:
            entries = _credited_order(entries, facets, sources)
        votes.extend(v for v, _ in entries)
    return votes


def _best_spelling(claims: list[ClaimRow], sources, facets: dict[int, _Facet]) -> Any:
    """The spelling backed by the most origin groups, then the highest-priority source, then
    the text itself."""
    backing: dict[str, set[str]] = defaultdict(set)
    priority: dict[str, int] = {}
    for c in claims:
        text = facets[id(c)].shown
        group, prio = _source(c.source, sources)
        backing[text].add(group)
        priority[text] = min(priority.get(text, prio), prio)
    return min(backing, key=lambda t: (-len(backing[t]), priority[t], t))


def _person_agree(facets: dict[int, _Facet]) -> Agree:
    """Spellings of one person agree (``same_person``)."""

    def agree(a: _Option, b: _Option) -> float:
        same = same_person(facets[id(a.claims[0])].shown, facets[id(b.claims[0])].shown)
        return 1.0 if same else 0.0

    return agree


def _credited_apart(a: _Option, b: _Option) -> bool:
    """Two names one record credits separately are two people."""
    return bool({c.record_id for c in a.claims} & {c.record_id for c in b.claims})


def _credited_order(entries: list[tuple[Vote, list[ClaimRow]]], facets, sources) -> list:
    """Reorder co-credits as the highest-priority record that credits two or more of them lists
    them; they take the places the ranking gave them, so other values keep theirs."""
    credits: dict[int, dict[int, int]] = defaultdict(dict)  # record -> {entry index: credit}
    source_of: dict[int, str] = {}
    for i, (_, claims) in enumerate(entries):
        for claim in claims:
            credit = facets[id(claim)].credit
            if credit is not None:
                held = credits[claim.record_id].get(i)
                credits[claim.record_id][i] = credit if held is None else min(held, credit)
                source_of[claim.record_id] = claim.source
    multi = [rid for rid, cr in credits.items() if len(cr) >= 2]
    if not multi:
        return entries

    def key(rid: int) -> tuple:
        listed = tuple(
            entries[i][0].norm
            for i in sorted(credits[rid], key=cast(Callable[[int], int], credits[rid].get))
        )
        return (_source(source_of[rid], sources)[1], -len(listed), source_of[rid], listed)

    chosen = credits[min(multi, key=key)]
    out = list(entries)
    for slot, i in zip(
        sorted(chosen), sorted(chosen, key=cast(Callable[[int], int], chosen.get)), strict=True
    ):
        out[slot] = entries[i]
    return out


def _position_vote(claims: list[ClaimRow], sources) -> Vote | None:
    """The series position, voted among the claims for one series name that give one."""
    placed = [c for c in claims if c.value[1] is not None]
    if not placed:
        return None
    return _scalar_vote(
        placed,
        sources,
        "series_position",
        norm=lambda c: f"{float(c.value[1]):g}",
        shown=lambda c: float(c.value[1]),
    )


def resolve_fields(
    claims: Iterable[ClaimRow], sources: Mapping[str, SourceInfo], *, entity: str
) -> dict[str, Vote | list[Vote]]:
    """Vote every field of one entity (``work`` or ``edition``) from its cluster's claims.

    Single-valued fields map to a ``Vote``; multi-valued ones to a ``list[Vote]``, keyed by the
    votes' ``field``, so people appear under their roles (``author``, ``editor``, ``narrator``,
    ``cover_artist``). Narrators belong to the work: the edition narrator list votes there with
    narrator credits, and the edition's own ``cover_artist`` scalar stays on the edition. The
    title vote is padded by the work's series and author/editor names. ``UNVOTED_FIELDS`` are
    left to the rebuild.
    """
    by_field: dict[str, list[ClaimRow]] = defaultdict(list)
    for claim in claims:
        if claim.field in WORK_FIELDS_FROM_EDITIONS:
            mine = entity == "work"
        else:
            mine = claim.entity == entity
        if mine:
            by_field[claim.field].append(claim)
    context = [strip_series_decoration(c.value[0]) for c in by_field.get("series", ())] + [
        c.value[0] for c in by_field.get("author", ()) if c.value[1] in ("author", "editor")
    ]

    out: dict[str, Vote | list[Vote]] = {}
    people = [c for f in sorted(PEOPLE_FIELDS) for c in by_field.pop(f, [])]
    for v in vote_multi(people, sources):
        out.setdefault(v.field, []).append(v)  # type: ignore[union-attr]
    for fld in sorted(by_field):
        if fld in UNVOTED_FIELDS:
            continue
        if fld in MULTI_FIELDS:
            for v in vote_multi(by_field[fld], sources):
                out.setdefault(v.field, []).append(v)  # type: ignore[union-attr]
        else:
            out[fld] = vote(by_field[fld], sources, context=context)  # type: ignore[assignment]
    return out


# --- disputed identifiers ------------------------------------------------------------------


def _idents(claim: ClaimRow) -> list[tuple[str, str]]:
    if claim.field in IDENT_FIELDS:
        return [(IDENT_FIELDS[claim.field], claim.value_norm)]
    if claim.field == "edition_id":
        kind, _, value = claim.value_norm.partition(":")
        return [(kind, value)] if kind and value else []
    return []


def disputed_idents(
    works: list[WorkCluster],
    claims: Mapping[int, list[ClaimRow]] | Iterable[ClaimRow],
    sources: Mapping[str, SourceInfo],
) -> dict[tuple[str, str], set[int]]:
    """Edition identifiers whose attachment to a work is disputed (spec 5.3.6).

    An identifier (ISBN-13, ASIN, Audible ASIN, or a source's edition id such as
    ``hardcover``/``openlibrary``/``goodreads``) is attached to a work by the origin groups of
    the work's records that claim it. The attachment to a work is disputed when exactly one
    origin group makes it while two or more groups attach the identifier to a different work.
    Only that minority side is disputed; the majority attachment stays ok, and two attachments
    of two or more groups each (or of one group each) dispute nothing.

    ``claims``: ``load_claims`` output or any ClaimRows; claims of records outside ``works``
    are ignored. Returns ``{(kind, value): {index in works of each disputed attachment}}``, so
    ``(kind, value) in result`` asks whether the identifier is disputed anywhere.
    """
    if isinstance(claims, Mapping):
        claims = [c for rows in claims.values() for c in rows]
    work_of = {rid: i for i, work in enumerate(works) for rid in work.record_ids}
    attached: dict[tuple[str, str], dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for claim in claims:
        idx = work_of.get(claim.record_id)
        if idx is None:
            continue
        for ident in _idents(claim):
            attached[ident][idx].add(_source(claim.source, sources)[0])

    out: dict[tuple[str, str], set[int]] = {}
    for ident, per_work in attached.items():
        if len(per_work) < 2 or not any(len(g) >= 2 for g in per_work.values()):
            continue
        weak = {idx for idx, groups in per_work.items() if len(groups) == 1}
        if weak:
            out[ident] = weak
    return out


# --- length class --------------------------------------------------------------------------


def length_class(words: int | None, pages: int | None) -> str | None:
    """short_story < 17,500 words <= novella < 50,000 <= novel (spec 5.3.8), from the word
    count when known, else pages x 250. Unknown (or non-positive) both: None."""
    if words is not None and words > 0:
        count = words
    elif pages is not None and pages > 0:
        count = pages * WORDS_PER_PAGE
    else:
        return None
    if count < SHORT_STORY_BELOW:
        return "short_story"
    return "novella" if count < NOVELLA_BELOW else "novel"
