"""Stable work and edition IDs (spec 4.3).

An ID is random (``secrets``), assigned once, and recorded in ``id_anchor`` against the
cluster's anchor. On every rebuild each cluster's candidate anchors are looked up and an
existing ID is reused:

- work anchor: Lexicanum page, else Wikidata QID, else Hardcover book id, else the work's
  earliest ISBN-13;
- edition anchor: ISBN-13, else ASIN, else Audible ASIN, else ``source:native_id``.

Every ``id_anchor`` row carries ``seq`` (its insertion order); an ID's age is the ``seq`` of its
oldest anchor. A cluster's claim on an ID is the oldest of that ID's anchors the cluster holds.

- Split: two clusters claim one ID. The stronger claim (the older anchor) keeps it, so the
  part holding the original anchor keeps the ID; the other part uses its next ID or a new one.
- Merge: one cluster keeps several IDs. The oldest ID survives; the others become
  ``id_alias`` rows pointing at it.

Every cluster must be able to pin the ID it gets, or a split-off part would get a new random ID
on every rebuild. So candidate lists end in anchors unique to the cluster: a work's smallest
edition key and its ``record`` anchor, an edition's ``record`` anchor (the smallest member
``source:native_id``). When even that is already recorded for the ID the cluster lost, the
cluster records a derived ``split`` anchor, ``<lost id>|<kind>:<value>`` of that last
candidate, and finds it again on the next rebuild. The other fallbacks (work identifiers
outside the spec's four) cover works the spec anchors miss.

Claims. A cluster claims an ID through any of the ID's anchors it holds, or through records
the previous rebuild linked to the ID (``record_link``, matched by ``source:native_id``, which
a re-fetch keeps). Strongest first:
1. a cluster holding one of the ID's anchors alone and some of the previous holder's records,
   by the anchor's age (the split rule above);
2. otherwise the best match to the previous holder (most of its records), then anchor age,
   then the number of the ID's anchors held, then the cluster's own last anchor.
List position never decides.

Shared anchors. Clusters the omnibus guard keeps apart can hold the same anchor (Hardcover
files an omnibus under one of its novels' book ids). An anchor held by two or more clusters in
this rebuild is never recorded, and its age decides nothing: the previous holder does. Each
cluster records its first anchor that is its own.
"""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Iterable, Mapping, Sequence

from bl_catalog.resolve.editions import EditionCluster
from bl_catalog.resolve.fields import ClaimRow, load_claims
from bl_catalog.resolve.works import WorkCluster

ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"  # base32, lowercase
ID_LENGTH = 10
PREFIX = {"work": "w_", "edition": "e_"}

# spec 4.3 precedence, then the fallbacks (module docstring)
WORK_ANCHOR_KINDS = ("lexicanum", "wikidata", "hardcover")
WORK_FALLBACK_KINDS = ("openlibrary_work", "fandom")
# edition cluster key prefix -> anchor kind, in precedence order
EDITION_ANCHOR_KINDS = {
    "isbn13": "isbn13",
    "asin": "asin",
    "audible": "audible_asin",
    "rec": "record",
}
_NO_DATE = "9999"

Anchor = tuple[str, str]  # (anchor_kind, anchor_value)


def new_id(entity: str, taken: Iterable[str] = ()) -> str:
    """A fresh random ID for ``entity`` (``work`` or ``edition``), not in ``taken``."""
    taken = taken if isinstance(taken, (set, frozenset, dict)) else set(taken)
    while True:
        out = PREFIX[entity] + "".join(secrets.choice(ALPHABET) for _ in range(ID_LENGTH))
        if out not in taken:
            return out


def _split_key(key: str) -> tuple[str, str]:
    kind, _, value = key.partition(":")
    return kind, value


def edition_anchors(edition: EditionCluster, record_key: str | None = None) -> list[Anchor]:
    """The cluster's candidate anchors, best first: its ISBN-13s, ASINs, Audible ASINs, then its
    ``record`` anchor. ``record_key`` is the smallest ``source:native_id`` of its member records;
    a keyless cluster's ``rec:`` key is the same thing."""
    order = list(EDITION_ANCHOR_KINDS)
    out = []
    for key in edition.keys:
        prefix, value = _split_key(key)
        if prefix in EDITION_ANCHOR_KINDS:
            out.append((order.index(prefix), EDITION_ANCHOR_KINDS[prefix], value))
    if record_key is not None:
        out.append((order.index("rec"), "record", record_key))
    return list(dict.fromkeys((kind, value) for _, kind, value in sorted(out)))


def release_dates(
    editions: Sequence[EditionCluster], claims: Mapping[int, list[ClaimRow]]
) -> dict[int, str]:
    """Earliest release date claimed by each edition cluster's records."""
    out: dict[int, str] = {}
    for i, ed in enumerate(editions):
        dates = [
            c.value_norm
            for rid in ed.record_ids
            for c in claims.get(rid, ())
            if c.field == "release_date" and c.value_norm[:4].isdigit()
        ]
        if dates:
            out[i] = min(dates)
    return out


def work_anchors(
    work: WorkCluster,
    editions: Sequence[EditionCluster],
    release_dates: Mapping[int, str] | None = None,
    record_key: str | None = None,
) -> list[Anchor]:
    """The work's candidate anchors, best first (spec 4.3, then the fallbacks).

    ISBN-13s are the work's edition keys (never an ISBN a record only claims), earliest release
    first, then by value. ``record_key`` (the smallest ``source:native_id`` of the work's
    records) adds the ``record`` anchor last, as editions have."""
    release_dates = release_dates or {}
    by_kind: dict[str, list[str]] = {}
    for key in work.work_keys:
        kind, value = _split_key(key)
        if value:
            by_kind.setdefault(kind, []).append(value)
    out: list[Anchor] = []
    for kind in WORK_ANCHOR_KINDS:
        out += [(kind, v) for v in sorted(by_kind.get(kind, ()))]
    isbns: dict[str, str] = {}
    for idx in work.edition_idx:
        for key in editions[idx].keys:
            prefix, value = _split_key(key)
            if prefix == "isbn13":
                when = release_dates.get(idx, _NO_DATE)
                isbns[value] = min(isbns.get(value, _NO_DATE), when)
    out += [("isbn13", v) for v in sorted(isbns, key=lambda v: (isbns[v], v))]
    for kind in WORK_FALLBACK_KINDS:
        out += [(kind, v) for v in sorted(by_kind.get(kind, ()))]
    for kind in sorted(set(by_kind) - set(WORK_ANCHOR_KINDS) - set(WORK_FALLBACK_KINDS)):
        out += [(kind, v) for v in sorted(by_kind[kind])]
    out.append(("edition", min(k for i in work.edition_idx for k in editions[i].keys)))
    if record_key is not None:
        out.append(("record", record_key))
    return out


def _split_anchor(lost: str, anchor: Anchor) -> Anchor:
    return ("split", f"{lost}|{anchor[0]}:{anchor[1]}")


def assign_anchored(
    conn: sqlite3.Connection,
    entity: str,
    candidates: Sequence[Sequence[Anchor]],
    taken: Iterable[str] = (),
    members: Sequence[Iterable[str]] | None = None,
) -> list[str]:
    """IDs for clusters given their candidate anchors (best first, ending in one unique to the
    cluster), one per cluster, in the order given.

    Splits, merges, shared anchors and the anchors recorded follow the module docstring.
    ``taken``: IDs already handed out in this rebuild, never handed out again. ``members``:
    each cluster's records as ``source:native_id`` (stable across re-fetches, unlike record
    ids), matched against the records the previous rebuild's ``record_link`` tied to each ID.
    Writes ``id_anchor`` and ``id_alias`` in the caller's transaction; aliases are flattened
    by ``flatten_aliases``."""
    known: dict[Anchor, tuple[int, str]] = {}
    age: dict[str, int] = {}
    anchors_of: dict[str, set[Anchor]] = {}
    for seq, id_, kind, value in conn.execute(
        "SELECT seq, id, anchor_kind, anchor_value FROM id_anchor WHERE entity=?", (entity,)
    ):
        known[(kind, value)] = (seq, id_)
        age[id_] = min(age.get(id_, seq), seq)
        anchors_of.setdefault(id_, set()).add((kind, value))

    cands: list[list[Anchor]] = []
    for given in candidates:
        mine = list(dict.fromkeys(given))
        if mine and mine[-1] in known:
            mine.append(_split_anchor(known[mine[-1]][1], mine[-1]))
        cands.append(mine)
    holders: dict[Anchor, int] = {}
    for mine in cands:
        for a in mine:
            holders[a] = holders.get(a, 0) + 1

    # previous holder: id -> how many of each cluster's records the last rebuild linked to it
    match: list[dict[str, int]] = [{} for _ in cands]
    if members is not None:
        linked: dict[str, set[str]] = {}  # source:native_id -> ids it was linked to
        for source, native, id_ in conn.execute(
            "SELECT r.source, r.native_id, rl.entity_id FROM record_link rl"
            " JOIN source_record r ON r.id = rl.record_id WHERE rl.entity=?",
            (entity,),
        ):
            linked.setdefault(f"{source}:{native}", set()).add(id_)
        for i, keys in enumerate(members):
            for key in set(keys):
                for id_ in linked.get(key, ()):
                    match[i][id_] = match[i].get(id_, 0) + 1

    def rank(i: int, id_: str) -> tuple:
        """Lower is a stronger claim (module docstring). First a cluster that holds one of the
        ID's anchors alone and has some of the previous holder's records, oldest anchor first
        (spec 4.3: the part holding the original anchor keeps the ID). Then the best match to
        the previous holder: a shared anchor, or an anchor alone with none of the holder's
        records, proves nothing. Then anchor age, the number of the ID's anchors held, and
        the cluster's own last anchor (unique, from the evidence; never list position)."""
        own = anchors_of.get(id_, set())
        alone = min(
            (known[a][0] for a in cands[i] if a in own and holders[a] == 1), default=float("inf")
        )
        matched = match[i].get(id_, 0)
        holds_it = matched > 0 and alone != float("inf")
        return (
            not holds_it,
            alone if holds_it else 0,
            -matched,
            alone,
            -sum(1 for a in cands[i] if a in own),
            cands[i][-1] if cands[i] else ("", ""),
        )

    used = set(taken)
    claim: dict[str, tuple[tuple, int]] = {}  # id -> (strongest claim's rank, cluster)
    for i, mine in enumerate(cands):
        ids_ = {known[a][1] for a in mine if a in known} | set(match[i])
        for id_ in ids_:
            if id_ in used or id_ not in age:
                continue
            r = rank(i, id_)
            if id_ not in claim or r < claim[id_][0]:
                claim[id_] = (r, i)
    won: dict[int, list[str]] = {}
    for id_, (_rank, i) in claim.items():
        won.setdefault(i, []).append(id_)

    every = {r[0] for r in conn.execute("SELECT id FROM id_anchor")}
    every |= {r[0] for r in conn.execute("SELECT old_id FROM id_alias")}
    every |= used
    out: list[str] = []
    aliases: list[tuple[str, str]] = []
    new_anchors: list[tuple[str, str, str, str]] = []
    for i, mine in enumerate(cands):
        mine_won = sorted(won.get(i, ()), key=lambda x: (age[x], x))
        if mine_won:
            id_ = mine_won[0]  # the oldest survives a merge
            aliases += [(old, id_) for old in mine_won[1:]]
        else:
            id_ = new_id(entity, every)
            every.add(id_)
        out.append(id_)
        if not mine:
            continue
        own = [a for a in mine if holders[a] == 1]  # a shared anchor is never recorded
        pin = None
        if own and own[0] not in known:
            pin = own[0]
        elif not mine_won:
            pin = next((a for a in own if a not in known), None)
        if pin is not None:
            new_anchors.append((entity, id_, *pin))
            known[pin] = (0, id_)  # recorded now: no later cluster records it again
    conn.executemany(
        "INSERT OR IGNORE INTO id_anchor (entity, id, anchor_kind, anchor_value) VALUES (?,?,?,?)",
        new_anchors,
    )
    conn.executemany(
        "INSERT OR REPLACE INTO id_alias (old_id, new_id) VALUES (?, ?)", sorted(aliases)
    )
    return out


def flatten_aliases(conn: sqlite3.Connection) -> None:
    """Point every alias straight at the end of its chain (B->A->C becomes B->C, A->C), so a
    lookup is one hop. Self-aliases and any cycle (never written by the resolver) are deleted:
    a cycle names no surviving ID."""
    edges = {old: new for old, new in conn.execute("SELECT old_id, new_id FROM id_alias")}
    final: dict[str, str | None] = {}
    for start in sorted(edges):
        path, node = [], start
        while node in edges and node not in final and node not in path:
            path.append(node)
            node = edges[node]
        end = final.get(node, node) if node not in path else None  # None: a cycle
        for p in path:
            final[p] = end
    for old, end in sorted(final.items()):
        if end is None or end == old:
            conn.execute("DELETE FROM id_alias WHERE old_id=?", (old,))
        elif end != edges[old]:
            conn.execute("UPDATE id_alias SET new_id=? WHERE old_id=?", (end, old))


def assign(
    conn: sqlite3.Connection,
    works: Sequence[WorkCluster],
    editions: Sequence[EditionCluster],
    *,
    claims: Mapping[int, list[ClaimRow]] | None = None,
    edition_idx: Iterable[int] | None = None,
) -> tuple[dict[int, str], dict[int, str]]:
    """``({work index: work id}, {edition index: edition id})`` (spec 4.3).

    ``claims`` is ``fields.load_claims`` output (loaded here when omitted; the rebuild passes
    the one it already has). ``edition_idx`` limits editions to those that become edition rows
    (default: all)."""
    claims = load_claims(conn) if claims is None else claims
    dates = release_dates(editions, claims)
    work_list = list(works)
    native = record_keys(conn)
    work_ids = assign_anchored(
        conn,
        "work",
        [work_anchors(w, editions, dates, work_record_key(w, native)) for w in work_list],
        members=[[native[r] for r in w.record_ids if r in native] for w in work_list],
    )
    wanted = sorted(range(len(editions)) if edition_idx is None else set(edition_idx))
    edition_ids = assign_anchored(
        conn,
        "edition",
        [
            edition_anchors(editions[i], min(native[r] for r in editions[i].record_ids))
            for i in wanted
        ],
        members=[[native[r] for r in editions[i].record_ids] for i in wanted],
    )
    return dict(enumerate(work_ids)), dict(zip(wanted, edition_ids, strict=True))


def work_record_key(work: WorkCluster, native: Mapping[int, str]) -> str | None:
    """The smallest ``source:native_id`` of the work's records: unique to the work."""
    keys = [native[r] for r in work.record_ids if r in native]
    return min(keys) if keys else None


def record_keys(conn: sqlite3.Connection) -> dict[int, str]:
    """``{record id: "source:native_id"}`` for every stored record."""
    return {
        rid: f"{source}:{native}"
        for rid, source, native in conn.execute("SELECT id, source, native_id FROM source_record")
    }
