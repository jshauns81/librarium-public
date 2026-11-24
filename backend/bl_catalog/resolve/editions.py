"""Edition clustering (spec 5.3 step 2): records that share an edition key are one edition.

Only *current* evidence counts. For each (source, native_id) the current record is the row
with the greatest ``last_seen_at`` (ties: the highest id), and a current record can still be
superseded by a later fetch of the same page (see ``_superseded``).
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from bl_catalog.config import SourceInfo, load_sources
from bl_catalog.resolve.titles import context_words, key_compatibility, title_key

# claim field -> key prefix. Only these identify an edition; ``isbn_invalid`` claims (a failed
# checksum) are evidence but never keys, and neither are per-source edition ids.
EDITION_KEY_FIELDS = {"isbn13": "isbn13", "asin": "asin", "audible_asin": "audible"}
COLLECTION_TYPES = frozenset({"omnibus", "anthology"})


@dataclass
class EditionCluster:
    record_ids: set[int] = field(default_factory=set)
    keys: set[str] = field(default_factory=set)
    # (record id, key): a single work's claim on a key a collection holds (spec 5.3.3). The
    # resolver drops these claims; the attachment is neither ok nor disputed.
    dropped: set[tuple[int, str]] = field(default_factory=set)


@dataclass(frozen=True)
class _Row:
    id: int
    source: str
    native_id: str
    seen: datetime


def current_records(conn: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    """``{record_id: (source, native_id)}`` for every current, non-superseded record."""
    best: dict[tuple[str, str], _Row] = {}
    for rid, source, native_id, seen in conn.execute(
        "SELECT id, source, native_id, last_seen_at FROM source_record"
    ):
        row = _Row(rid, source, native_id, datetime.fromisoformat(seen))
        held = best.get((source, native_id))
        if held is None or (row.seen, row.id) > (held.seen, held.id):
            best[(source, native_id)] = row

    pages: dict[tuple[str, str], list[_Row]] = defaultdict(list)
    for row in best.values():
        pages[(row.source, row.native_id.split("#", 1)[0])].append(row)
    dropped = {
        row.id for rows in pages.values() if len(rows) > 1 for row in _superseded(rows)
    }  # fmt: skip
    return {row.id: (row.source, row.native_id) for row in best.values() if row.id not in dropped}


def _superseded(rows: list[_Row]) -> list[_Row]:
    """The records of one page or item (a ``base`` native_id and its ``base#…`` siblings) that
    its latest fetch did not yield again.

    Lexicanum, Fandom, Wikidata and Wikipedia store one page's or item's editions (or series
    members, or bibliography entries) as ``base#…`` records, and a single-edition page as a
    plain ``base`` record. When the page changes between fetches the old rows stay current under
    their own native_ids. Every record of one fetch is stamped with one identical
    ``last_seen_at`` (one stamp per Lexicanum page, one per harvest query), so the rows of the
    latest fetch are exactly those carrying the newest stamp; anything older is a leftover.
    """
    latest = max(row.seen for row in rows)
    return [row for row in rows if row.seen < latest]


def cluster_editions(
    conn: sqlite3.Connection, sources: Mapping[str, SourceInfo] | None = None
) -> list[EditionCluster]:
    """Union-find over current records sharing an ISBN-13, ASIN or Audible ASIN.

    A key unites records unless their titles are clearly different works (one source lists
    another book's ISBN). The test is lenient (``titles.key_compatibility``): a truncated or
    decorated feed title ("Seeds", "Horus Rising Book 1") stays on the key. Clearly different
    titles split into title families (``_families``): each family unites on the key among
    itself, and only the top family holds the key (a collection, else the most origin groups).
    The others keep it as a claim, never as a key, so the mis-listed record stays with its own
    book and ``fields.disputed_idents`` judges the attachment from the finished works (spec
    5.3.6). A single work's family that loses a key to a collection does not keep the claim: it
    is listed in ``EditionCluster.dropped`` and the resolver drops it (spec 5.3.3).

    A cluster with no edition key is keyed ``rec:<source>:<native_id>`` (its smallest). Clusters
    are ordered by their smallest record id, so the same evidence always gives the same list.
    """
    sources = load_sources() if sources is None else sources
    records = current_records(conn)
    parent = {rid: rid for rid in records}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    holders: dict[str, list[int]] = defaultdict(list)
    marks = ",".join("?" * len(EDITION_KEY_FIELDS))
    for rid, fld, norm in conn.execute(
        f"SELECT record_id, field, value_norm FROM claim WHERE field IN ({marks})"
        " ORDER BY record_id",
        tuple(EDITION_KEY_FIELDS),
    ):
        if rid in records:
            holders[f"{EDITION_KEY_FIELDS[fld]}:{norm}"].append(rid)

    shared = {rid for rids in holders.values() if len(rids) > 1 for rid in rids}
    titles = _title_facts(conn, shared)
    record_keys: dict[int, set[str]] = defaultdict(set)
    dropped: dict[int, set[str]] = defaultdict(set)
    for key in sorted(holders):
        families = _families(holders[key], titles, records, sources)
        top_is_collection = len(families) > 1 and _collection(families[0], titles)
        for rank, family in enumerate(families):
            first, *rest = sorted(family)
            for rid in rest:
                a, b = find(first), find(rid)
                if a != b:
                    parent[max(a, b)] = min(a, b)
            if rank == 0:
                for rid in family:
                    record_keys[rid].add(key)
            elif top_is_collection and not _collection(family, titles):
                for rid in family:
                    dropped[rid].add(key)

    groups: dict[int, EditionCluster] = {}
    for rid in sorted(records):
        cluster = groups.setdefault(find(rid), EditionCluster())
        cluster.record_ids.add(rid)
        cluster.keys |= record_keys.get(rid, set())
        cluster.dropped |= {(rid, key) for key in dropped.get(rid, ())}
    for cluster in groups.values():
        if not cluster.keys:
            cluster.keys.add(
                min(f"rec:{records[r][0]}:{records[r][1]}" for r in cluster.record_ids)
            )
    return sorted(groups.values(), key=lambda c: min(c.record_ids))


@dataclass
class _Title:
    key: str  # title_key
    context: frozenset[str]
    collection: bool = False  # an omnibus/anthology (``_collection``)


def _title_facts(conn: sqlite3.Connection, record_ids: set[int]) -> dict[int, _Title]:
    """Title key and padding context (series and author words) of each record that shares a
    key with another; records without a title are absent."""
    if not record_ids:
        return {}
    raw: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for rid, fld, value in conn.execute(
        "SELECT record_id, field, value FROM claim"
        " WHERE field IN ('title', 'series', 'author', 'type')"
    ):
        if rid in record_ids:
            raw[rid][fld].append(json.loads(value))
    out = {}
    for rid, f in raw.items():
        if f["title"]:
            context = context_words([s[0] for s in f["series"]], [a[0] for a in f["author"]])
            types = {str(t).strip().lower() for t in f["type"]}
            # only a stated type: one untyped "... Collection" title must not outrank a novel
            out[rid] = _Title(title_key(min(f["title"])), context, bool(types & COLLECTION_TYPES))
    return out


def _collection(family: list[int], titles: dict[int, _Title]) -> bool:
    """Is this title family an omnibus/anthology? Any titled member whose stated type says so
    makes it one."""
    return any(titles[r].collection for r in family if r in titles)


def _families(
    rids: list[int],
    titles: dict[int, _Title],
    records: dict[int, tuple[str, str]],
    sources: Mapping[str, SourceInfo],
) -> list[list[int]]:
    """Split the records holding one key into title families, best first.

    Titles are grouped by title key and ranked by origin groups, then the lowest source
    priority, then the key. One exception, the omnibus trap (spec 5.3.3): a family whose records
    state an omnibus/anthology type ranks first when no single-work family has more origin
    groups than it, since a novel page listing its collection's ISBN is the usual cause. Pass 1 picks anchors: a title compatible with no earlier anchor
    (``key_compatibility``) starts a family. Pass 2 puts every other title in the family of the
    anchor it fits best (earliest anchor on a tie). Anchoring, not chaining: a title that fits
    two incompatible anchors cannot bridge them. Families rank like titles; records without a title
    are neutral and join the first. One family (the usual case) is the whole list.
    """
    by_title: dict[str, list[int]] = defaultdict(list)
    for rid in rids:
        if rid in titles:
            by_title[titles[rid].key].append(rid)
    if len(by_title) <= 1:
        return [rids]

    def groups(members: list[int]) -> int:
        return len({_info(records[r][0], sources)[0] for r in members})

    def base(members: list[int], tkey: str) -> tuple:
        infos = [_info(records[r][0], sources) for r in members]
        return (-len({g for g, _ in infos}), min(p for _, p in infos), tkey)

    support = {
        True: max((groups(m) for m in by_title.values() if _collection(m, titles)), default=0),
        False: max((groups(m) for m in by_title.values() if not _collection(m, titles)), default=0),
    }  # fmt: skip
    collection_first = support[True] > 0 and support[False] <= support[True]

    def rank(members: list[int], tkey: str) -> tuple:
        single = not _collection(members, titles)
        return (single if collection_first else False, *base(members, tkey))

    def context(tkey: str) -> frozenset[str]:
        return frozenset().union(*(titles[r].context for r in by_title[tkey]))

    ordered = sorted(by_title, key=lambda f: rank(by_title[f], f))
    anchors: list[str] = []
    for tkey in ordered:
        if not any(key_compatibility(a, tkey, context(a) | context(tkey)) for a in anchors):
            anchors.append(tkey)
    members: dict[str, list[int]] = {a: list(by_title[a]) for a in anchors}
    for tkey in ordered:
        if tkey in members:
            continue
        best = max(
            range(len(anchors)),
            key=lambda i: (
                key_compatibility(anchors[i], tkey, context(anchors[i]) | context(tkey)),
                -i,
            ),
        )
        members[anchors[best]] += by_title[tkey]
    families = sorted(members.items(), key=lambda item: rank(item[1], item[0]))
    out = [list(rids_) for _, rids_ in families]
    out[0] += [rid for rid in rids if rid not in titles]
    return out


def _info(source: str, sources: Mapping[str, SourceInfo]) -> tuple[str, int]:
    info = sources.get(source)
    return (info.origin_group, info.priority) if info else (source, 9)
