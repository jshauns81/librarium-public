"""The full rebuild: evidence -> resolved tables (spec 4.2, 5.3).

``rebuild`` clusters editions and works (Task 10), votes every field (``fields``), assigns stable
IDs (``ids``), links contents (``contents``) and rewrites every resolved table except
``id_anchor`` and ``id_alias``, which only grow. It all happens in ONE transaction: a crash or a
SIGKILL part-way leaves the previous resolved tables exactly as they were.

What becomes what:
- a work cluster with a title (or, failing that, an alias) is a ``work``; one with neither
  (an identifier-only stray) is skipped;
- an edition cluster becomes an ``edition`` only when its records make edition claims. Lexicanum
  series-membership and redirect-alias records make none: they join their work through
  ``work_ids`` and add only series membership and aliases;
- an ``author`` is one person (``people.cluster`` over every credited name): ``author.name`` is
  the canonical spelling and ``author_alias`` holds the others, so a work's voted display name
  (``Vote.value``, kept in its ``field_support``) is the name or one of the aliases.
  ``work_author`` rows are written in the vote's credited order, so the API's primary author is
  the vote's first;
- every current record is linked (``record_link``) to its work and, when it made one, its
  edition; records of a skipped cluster are not.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from bl_catalog.config import SourceInfo, load_sources
from bl_catalog.covers import rebuild_work_covers
from bl_catalog.isbn import isbn10_of
from bl_catalog.publish import resolved_hash
from bl_catalog.resolve import contents, ids, people
from bl_catalog.resolve.editions import EditionCluster, cluster_editions
from bl_catalog.resolve.fields import (
    ClaimRow,
    Vote,
    disputed_idents,
    length_class,
    load_claims,
    resolve_fields,
    series_key,
)
from bl_catalog.resolve.titles import fold_possessive
from bl_catalog.resolve.works import WORK_ID_KINDS, WorkCluster, cluster_works

# Deleted children first (foreign keys are on). id_anchor and id_alias are never deleted.
REBUILT_TABLES = (
    "work_cover",
    "field_support",
    "record_link",
    "work_contains",
    "work_tag",
    "work_alias",
    "work_series",
    "work_author",
    "work_ident",
    "edition_ident",
    "edition",
    "series",
    "author_alias",
    "author",
    "work",
)
ROLES = ("author", "editor", "narrator", "cover_artist")  # work_author.role
TAG_KINDS = frozenset({"faction", "character", "planet"})  # work_tag.kind
IDENT_CLAIMS = {"isbn13": "isbn13", "asin": "asin", "audible_asin": "audible_asin"}
WORK_TYPES = frozenset(
    {"novel", "novella", "short_story", "audio_drama", "omnibus", "anthology", "script_book",
     "other"}
)  # fmt: skip
_INT_COLUMNS = frozenset({"word_count", "pages", "runtime_minutes"})
_DATE = re.compile(r"\d{4}(?:-\d{2}(?:-\d{2})?)?")


@dataclass(frozen=True)
class RebuildReport:
    works: int
    editions: int
    disputed: int  # edition identifiers written with status 'disputed' (ISBN-10 twins not counted)
    changed: bool
    seconds: float = 0.0
    skipped: int = 0  # work clusters with neither a title nor an alias


def rebuild(
    conn: sqlite3.Connection, sources: Mapping[str, SourceInfo] | None = None
) -> RebuildReport:
    """Rebuild every resolved table from the evidence in one transaction (see module doc).
    ``changed`` compares ``publish.resolved_hash`` before and after."""
    sources = load_sources() if sources is None else sources
    started = time.monotonic()
    if conn.in_transaction:
        conn.commit()  # never fold a caller's pending writes into our rollback
    before = resolved_hash(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        counts = _rebuild(conn, sources)
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
    return RebuildReport(
        **counts,
        changed=resolved_hash(conn) != before,
        seconds=round(time.monotonic() - started, 2),
    )


# --- the steps ---------------------------------------------------------------------------------


def _rebuild(conn: sqlite3.Connection, sources) -> dict:
    w: Any
    editions = cluster_editions(conn, sources)
    all_works = cluster_works(conn, editions)
    claims = load_claims(conn)  # once, for the whole database
    _drop_attachments(claims, editions)

    def claims_of(record_ids) -> list[ClaimRow]:
        return [c for rid in sorted(record_ids) for c in claims.get(rid, ())]

    works: list[WorkCluster] = []
    work_votes: list[dict] = []
    skipped = 0
    for w in all_works:
        votes = resolve_fields(claims_of(w.record_ids), sources, entity="work")
        if votes.get("title") is None and not votes.get("alias"):
            skipped += 1
            continue
        works.append(w)
        work_votes.append(votes)

    edition_votes: dict[int, dict] = {}
    edition_claims: dict[int, list[ClaimRow]] = {}
    for w in works:
        for i in w.edition_idx:
            ed_claims = [c for c in claims_of(editions[i].record_ids) if c.entity == "edition"]
            if ed_claims:
                edition_claims[i] = ed_claims
                edition_votes[i] = resolve_fields(ed_claims, sources, entity="edition")

    disputed = disputed_idents(works, claims, sources)
    work_ids, edition_ids = ids.assign(
        conn, works, editions, claims=claims, edition_idx=edition_votes
    )

    for table in REBUILT_TABLES:
        conn.execute(f'DELETE FROM "{table}"')

    w = _Writer(conn, edition_claims, sources)
    dates = ids.release_dates(editions, claims)
    work_info: dict[int, contents.WorkInfo] = {}
    for idx, (cluster, votes) in enumerate(zip(works, work_votes, strict=True)):
        anchors = ids.work_anchors(cluster, editions, dates)  # as ids.assign builds them
        info = w.work(
            work_ids[idx], cluster, votes, editions, edition_votes, edition_ids, disputed, idx
        )
        info.stable = f"{anchors[0][0]}:{anchors[0][1]}"
        work_info[idx] = info

    links = contents.link(conn, works, work_ids, claims=claims, sources=sources, info=work_info)
    for child in links.created:
        w.child(child)
    w.rows["work_contains"] = list(links)
    w.rows["record_link"] = _record_links(
        works, editions, claims, work_ids, edition_ids, links.created
    )
    w.flush()
    _write_links(conn, w.rows["record_link"])
    rebuild_work_covers(conn)
    _tidy_aliases(conn)
    return {
        "works": len(w.rows["work"]),
        "editions": len(w.rows["edition"]),
        "disputed": sum(
            1 for r in w.rows["edition_ident"] if r[3] == "disputed" and r[1] != "isbn10"
        ),
        "skipped": skipped,
    }


def _drop_attachments(
    claims: dict[int, list[ClaimRow]], editions: Sequence[EditionCluster]
) -> None:
    """Remove a single work's claims on a key its collection holds (``EditionCluster.dropped``):
    only those key claims. Every other claim stays, so a record whose only key was the lost
    one is still an (ISBN-less) edition of its own work."""
    for ed in editions:
        gone: dict[int, set[str]] = defaultdict(set)
        for rid, key in ed.dropped:
            gone[rid].add(key)
        for rid, keys in gone.items():
            claims[rid] = [c for c in claims.get(rid, []) if _claim_key(c) not in keys]


def _claim_key(c: ClaimRow) -> str | None:
    prefix = _KEY_PREFIX.get(c.field)
    return f"{prefix}:{c.value_norm}" if prefix else None


def _write_links(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    conn.executemany(
        "INSERT INTO record_link (record_id, entity, entity_id, reason) VALUES (?,?,?,?)", rows
    )


def _tidy_aliases(conn: sqlite3.Connection) -> None:
    """An ID that is live again (a split gave it back) is no longer an alias of anything, and
    chains are flattened to one hop."""
    conn.execute(
        "DELETE FROM id_alias WHERE old_id IN (SELECT id FROM work UNION SELECT id FROM edition)"
    )
    ids.flatten_aliases(conn)


# --- rows --------------------------------------------------------------------------------------


def _value(vote: Vote | None):
    return None if vote is None else vote.value


def _int(value) -> int | None:
    try:
        return int(float(value))
    except TypeError, ValueError:
        return None


def _float(value) -> float | None:
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def sort_title(title: str) -> str:
    """The title as plain words: 'Cain's Last Stand' -> 'Cains Last Stand'."""
    return " ".join(re.findall(r"\w+", fold_possessive(title))) or title


def sort_name(name: str) -> str:
    """'Dan Abnett' -> 'Abnett, Dan'; a single word stays as it is."""
    parts = name.split()
    return f"{parts[-1]}, {' '.join(parts[:-1])}" if len(parts) > 1 else name


def _lower_median(values: list[int]) -> int | None:
    values = sorted(values)
    return values[(len(values) - 1) // 2] if values else None


class _Writer:
    """Collects the resolved rows, then writes them with one executemany per table."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        edition_claims: Mapping[int, list[ClaimRow]],
        sources: Mapping[str, SourceInfo],
    ) -> None:
        self.conn = conn
        self.edition_claims = edition_claims
        self.sources = sources
        self.rows: dict[str, list[tuple]] = {t: [] for t in REBUILT_TABLES}
        self.credits: list[tuple[str, str, str]] = []  # (work_id, name, role), credited order
        self.spelling_works: dict[str, set[str]] = defaultdict(set)  # spelling -> observed works
        # (work_id, name as the work's vote shows it, position, origin groups behind it)
        self.memberships: list[tuple[str, str, float | None, int]] = []

    def support(self, entity: str, entity_id: str, vote: Vote, field: str | None = None) -> None:
        row = vote.support_row()
        self.rows["field_support"].append(
            (entity, entity_id, field or row["field"], row["value"], row["score"],
             row["agree_json"], row["disagree_json"])
        )  # fmt: skip

    def work(
        self,
        wid: str,
        cluster: WorkCluster,
        votes: dict,
        editions: Sequence[EditionCluster],
        edition_votes: Mapping[int, dict],
        edition_ids: Mapping[int, str],
        disputed: Mapping[tuple[str, str], set[int]],
        work_idx: int,
    ) -> contents.WorkInfo:
        aliases = [v.value for v in votes.get("alias", [])]
        title_vote = votes.get("title")
        title = title_vote.value if title_vote else aliases[0]
        # A sparse old page can win the title vote after a redirect merge. Keep both page
        # spellings so searches and contents entries still find the former canonical title.
        aliases.extend(sorted(cluster.redirect_titles))

        pages, dates = [], []
        for i in sorted(cluster.edition_idx):
            ev = edition_votes.get(i)
            if ev is None:
                continue
            if (p := _int(_value(ev.get("pages")))) and p > 0:
                pages.append(p)
            if (d := _value(ev.get("release_date"))) and _DATE.fullmatch(str(d)):
                dates.append(str(d))
            self.edition(edition_ids[i], wid, self.edition_claims[i], ev, disputed, work_idx)

        word_count = _int(_value(votes.get("word_count")))
        klass = length_class(word_count, _lower_median(pages))
        stated = _value(votes.get("type"))
        type_ = stated if stated in WORK_TYPES else (klass or None)
        first = _value(votes.get("first_published")) or (min(dates) if dates else None)
        self.rows["work"].append(
            (wid, title, sort_title(title), type_, _value(votes.get("setting")),
             _value(votes.get("synopsis")), word_count, klass, first)
        )  # fmt: skip

        for fld, entry in votes.items():
            for vote in entry if isinstance(entry, list) else [entry]:
                if vote is None:
                    continue
                self.support("work", wid, vote)
                if vote.field in ROLES:
                    self.credits.append((wid, vote.value, vote.field))
                    for name in {vote.value, *vote.extra.get("spellings", ())}:
                        self.spelling_works[name].add(wid)
                elif fld == "series":
                    position = vote.extra.get("position")
                    pos = _float(position.value) if isinstance(position, Vote) else None
                    self.memberships.append((wid, vote.value, pos, len(vote.agree)))
                    if isinstance(position, Vote):
                        self.support("work", wid, position, "series_position")
                elif fld == "tag" and vote.extra.get("kind") in TAG_KINDS:
                    self.rows["work_tag"].append((wid, vote.extra["kind"], vote.value))
        for alias in dict.fromkeys(aliases):
            if alias != title:
                self.rows["work_alias"].append((wid, alias))
        for key in sorted(cluster.work_keys):
            kind, _, value = key.partition(":")
            if kind and value:
                self.rows["work_ident"].append((wid, kind, value))
        authors = [v.value for v in votes.get("author", [])]
        return contents.WorkInfo(titles=[title, *aliases], authors=authors, type=type_, stable=wid)

    def edition(
        self,
        eid: str,
        wid: str,
        ed_claims: list[ClaimRow],
        votes: dict,
        disputed: Mapping[tuple[str, str], set[int]],
        work_idx: int,
    ) -> None:
        def status(kind: str, value: str) -> str:
            return "disputed" if work_idx in disputed.get((kind, value), ()) else "ok"

        idents: dict[tuple[str, str], str] = {}
        for kind, value in _idents(ed_claims):  # every identifier the records claim
            idents[(kind, value)] = status(kind, value)
            if kind == "isbn13" and (ten := isbn10_of(value)):
                idents[("isbn10", ten)] = idents[(kind, value)]

        isbn13 = _value(votes.get("isbn13"))
        if isbn13 and idents.get(("isbn13", isbn13)) == "disputed":
            ok = sorted(v for (k, v), s in idents.items() if k == "isbn13" and s == "ok")
            if ok:  # never show a disputed ISBN while the edition has an ok one
                isbn13 = ok[0]
                votes = {**votes, "isbn13": _support_for(ed_claims, isbn13, self.sources)}
        in_print = _value(votes.get("in_print"))
        self.rows["edition"].append(
            (eid, wid, _value(votes.get("format")), isbn10_of(isbn13) if isbn13 else None, isbn13,
             _value(votes.get("asin")), _value(votes.get("audible_asin")),
             _value(votes.get("publisher")), _value(votes.get("imprint")),
             _value(votes.get("release_date")), _value(votes.get("region")),
             _int(_value(votes.get("pages"))), _int(_value(votes.get("runtime_minutes"))),
             _value(votes.get("cover_artist")), _value(votes.get("cover_url")),
             _float(_value(votes.get("price"))), _value(votes.get("price_currency")),
             None if in_print is None else int(bool(in_print)))
        )  # fmt: skip
        for (kind, value), st in sorted(idents.items()):
            self.rows["edition_ident"].append((eid, kind, value, st))
        for entry in votes.values():
            for vote in entry if isinstance(entry, list) else [entry]:
                if vote is not None:
                    self.support("edition", eid, vote)

    def child(self, child: contents.ChildWork) -> None:
        """A work created from contents entries."""
        self.rows["work"].append(
            (child.id, child.title, sort_title(child.title), child.type, None, None, None, None,
             None)
        )  # fmt: skip
        groups = sorted(child.groups)
        for fld, value, stated in (
            ("title", child.title, True),
            ("type", child.type, child.type_stated),
        ):
            if stated:
                self.support("work", child.id, Vote(value, 1.0, groups, [], field=fld))
        for name in child.authors:
            self.credits.append((child.id, name, "author"))
            self.spelling_works[name].add(child.id)
            self.support("work", child.id, Vote(name, 1.0, groups, [], field="author"))

    def flush(self) -> None:
        # One author per person (resolve/people.py), named by the canonical spelling, with the
        # other spellings kept as aliases. A work crediting two spellings of one person in one
        # role credits that person once.
        # Include every observed spelling in the partition, not just the display winners.
        # Otherwise a noisy winner can hide the clean canonical name, or acquire an alias
        # that is also a different person's canonical name when initials are ambiguous.
        persons = people.cluster({name: len(wids) for name, wids in self.spelling_works.items()})
        number = {canon: i for i, canon in enumerate(sorted(persons), 1)}
        person = {n: number[canon] for canon, spellings in persons.items() for n in spellings}
        self.rows["author"] = [(number[c], c, sort_name(c)) for c in sorted(persons)]
        # Every spelling belongs to exactly one person, including ambiguous initials.
        self.rows["author_alias"] = [
            (number[c], n) for c in sorted(persons) for n in sorted(set(persons[c]) - {c})
        ]
        seen: set[tuple] = set()
        for wid, name, role in self.credits:
            key = (wid, person[name], role)
            if key not in seen:
                seen.add(key)
                self.rows["work_author"].append(key)
        # One series per series_key across all works ("Horus Heresy" on one work and "The
        # Horus Heresy" on another are one series), named by the spelling with the most
        # support over every work (origin groups summed), then alphabetically.
        support: dict[str, Counter[str]] = defaultdict(Counter)
        for _, name, _, groups in self.memberships:
            support[series_key(name)][name] += groups
        shown = {k: min(c, key=lambda n: (-c[n], n)) for k, c in support.items()}
        number = {k: i for i, k in enumerate(sorted(shown, key=lambda k: (shown[k], k)), 1)}
        self.rows["series"] = [
            (number[k], shown[k])
            for k in sorted(number, key=cast(Callable[[str], int], number.get))
        ]
        seen = set()
        for wid, name, pos, _ in self.memberships:
            sid = number[series_key(name)]
            if (wid, sid) not in seen:
                seen.add((wid, sid))
                self.rows["work_series"].append((wid, sid, pos))
        self.rows["work_alias"] = list(dict.fromkeys(self.rows["work_alias"]))
        self.rows["work_tag"] = list(dict.fromkeys(self.rows["work_tag"]))

        sql = {
            "work": "INSERT INTO work (id, title, sort_title, type, setting, synopsis,"
            " word_count, length_class, first_published) VALUES (?,?,?,?,?,?,?,?,?)",
            "edition": "INSERT INTO edition (id, work_id, format, isbn10, isbn13, asin,"
            " audible_asin, publisher, imprint, release_date, region, pages, runtime_minutes,"
            " cover_artist, cover_url, price, price_currency, in_print)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            "edition_ident": "INSERT INTO edition_ident (edition_id, kind, value, status)"
            " VALUES (?,?,?,?)",
            "work_ident": "INSERT OR IGNORE INTO work_ident (work_id, kind, value) VALUES (?,?,?)",
            "author": "INSERT INTO author (id, name, sort_name) VALUES (?,?,?)",
            "author_alias": "INSERT INTO author_alias (author_id, name) VALUES (?,?)",
            "work_author": "INSERT INTO work_author (work_id, author_id, role) VALUES (?,?,?)",
            "series": "INSERT INTO series (id, name) VALUES (?,?)",
            "work_series": "INSERT INTO work_series (work_id, series_id, position) VALUES (?,?,?)",
            "work_alias": "INSERT INTO work_alias (work_id, title) VALUES (?,?)",
            "work_tag": "INSERT INTO work_tag (work_id, kind, value) VALUES (?,?,?)",
            "work_contains": "INSERT INTO work_contains (parent_id, child_id, position)"
            " VALUES (?,?,?)",
            "field_support": "INSERT INTO field_support (entity, entity_id, field, value, score,"
            " agree_json, disagree_json) VALUES (?,?,?,?,?,?,?)",
        }
        for table in ("work", "edition", "edition_ident", "work_ident", "author", "author_alias",
                      "work_author",
                      "series", "work_series", "work_alias", "work_tag", "work_contains",
                      "field_support"):  # fmt: skip
            self.conn.executemany(sql[table], self.rows[table])


def _support_for(ed_claims: list[ClaimRow], isbn13: str, sources) -> Vote:
    """The ``isbn13`` support of a chosen value that is not the vote's winner (the winner was
    disputed): the groups giving it agree, the others dissent with their values."""

    def group(c: ClaimRow) -> str:
        info = sources.get(c.source)
        return info.origin_group if info else c.source

    claims = [c for c in ed_claims if c.field == "isbn13"]
    every = {group(c) for c in claims}
    agree = {group(c) for c in claims if c.value_norm == isbn13}
    dissent = sorted({(group(c), c.value_norm) for c in claims if c.value_norm != isbn13})
    return Vote(
        value=isbn13,
        score=round(len(agree) / len(every), 2),
        agree=sorted(agree),
        disagree=[{"origin": g, "value": v} for g, v in dissent],
        field="isbn13",
        norm=isbn13,
    )


def _idents(ed_claims: list[ClaimRow]) -> list[tuple[str, str]]:
    """(kind, value) of every edition identifier claimed: ISBN-13s, ASINs, Audible ASINs and
    source edition ids (``hardcover``, ``openlibrary``, ``goodreads``...), as
    ``fields.disputed_idents`` names them."""
    found: set[tuple[str, str]] = set()
    for c in ed_claims:
        if c.field in IDENT_CLAIMS:
            found.add((IDENT_CLAIMS[c.field], c.value_norm))
        elif c.field == "edition_id":
            kind, _, value = c.value_norm.partition(":")
            if kind and value:
                found.add((kind, value))
    return sorted(found)


# --- provenance --------------------------------------------------------------------------------


def _record_links(
    works: Sequence[WorkCluster],
    editions: Sequence[EditionCluster],
    claims: Mapping[int, list[ClaimRow]],
    work_ids: Mapping[int, str],
    edition_ids: Mapping[int, str],
    created: Sequence[contents.ChildWork],
) -> list[tuple]:
    """``(record_id, entity, entity_id, reason)`` for every record of every written work.

    Edition reason: the edition key the record holds (``isbn13:…``, ``asin:…``, ``audible:…``),
    or ``record`` for a one-record edition. Work reason: ``edition`` when the work is one edition
    cluster, ``work_id:<kind:value>`` when its cluster shares a work identifier with another
    cluster of the work, else ``title+author``. Created children: ``contents``."""
    out: list[tuple] = []
    for w_idx, work in enumerate(works):
        wid = work_ids[w_idx]
        keys_of: dict[int, set[str]] = {}
        clusters_with: Counter[str] = Counter()  # work id key -> edition clusters holding it
        for i in work.edition_idx:
            keys_of[i] = {
                c.value_norm
                for rid in editions[i].record_ids
                for c in claims.get(rid, ())
                if c.field == "work_id" and c.value_norm.split(":", 1)[0] in WORK_ID_KINDS
            }
            keys_of[i].update(
                work.redirect_keys[rid]
                for rid in editions[i].record_ids
                if rid in work.redirect_keys
            )
            clusters_with.update(keys_of[i])
        for i in sorted(work.edition_idx):
            ed = editions[i]
            if len(work.edition_idx) == 1:
                reason = "edition"
            else:
                shared = sorted(k for k in keys_of[i] if clusters_with[k] > 1)
                reason = f"work_id:{shared[0]}" if shared else "title+author"
            for rid in sorted(ed.record_ids):
                out.append((rid, "work", wid, reason))
                if i in edition_ids:
                    out.append((rid, "edition", edition_ids[i], _edition_reason(ed, rid, claims)))
    for child in created:
        for rid in sorted(child.record_ids):
            out.append((rid, "work", child.id, "contents"))
    return out


_KEY_PREFIX = {"isbn13": "isbn13", "asin": "asin", "audible_asin": "audible"}


def _edition_reason(ed: EditionCluster, rid: int, claims: Mapping[int, list[ClaimRow]]) -> str:
    if len(ed.record_ids) == 1:
        return "record"
    held = sorted(
        f"{_KEY_PREFIX[c.field]}:{c.value_norm}"
        for c in claims.get(rid, ())
        if c.field in _KEY_PREFIX and f"{_KEY_PREFIX[c.field]}:{c.value_norm}" in ed.keys
    )
    return held[0] if held else "record"
