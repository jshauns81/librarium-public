"""Contents linking (spec 5.3 step 7): contents claims become ``work_contains`` edges.

For each parent work, the contents entries of all its records are merged by title (one entry
per child, whichever sources list it). Each merged entry is matched to a work by title
agreement (``names.agreement >= 0.9``) and author agreement (``author_agreement >= 0.6``, names
un-inverted). An entry without authors of its own is credited to the parent's authors: the
stories of an omnibus are its author's, and an anthology's author credits name its
contributors. An entry that matches no work becomes a new child work (its own type, default
``short_story``); the same story listed by two parents becomes one child.

Guards:
- a parent never contains itself, so an omnibus's own title in its contents never self-links;
- the omnibus trap: a collection (omnibus/anthology) and a single work only match when their
  titles are equal word for word, and never when both state types that disagree on it;
- an edge that would close a cycle is dropped. Edges are added best first (source priority,
  then the parent's and child's content-derived keys), so the dropped edge is always the same.

Positions come from the highest-priority source that gives one; Wikidata may give none, and
those entries sort last.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import cast

from bl_catalog.config import SourceInfo
from bl_catalog.names import (
    BOILERPLATE,
    agreement,
    author_agreement,
    normalise,
    undecorate,
    uninvert,
)
from bl_catalog.resolve import ids
from bl_catalog.resolve.fields import ClaimRow
from bl_catalog.resolve.titles import PADDING, key_agreement, title_key
from bl_catalog.resolve.works import WorkCluster

TITLE_AGREEMENT = 0.9
AUTHOR_AGREEMENT = 0.6
COLLECTION_TYPES = frozenset({"omnibus", "anthology"})
COLLECTION_WORDS = frozenset({"omnibus", "anthology", "collection"})
DEFAULT_TYPE = "short_story"
_DEFAULT_PRIORITY = 9


@dataclass
class WorkInfo:
    """What linking needs to know about a resolved work."""

    titles: list[str]  # the voted title first, then its aliases
    authors: list[str]  # author-role display names, credited order
    type: str | None
    stable: str  # a content-derived key (its best anchor), for a deterministic order

    @property
    def collection(self) -> bool:
        if self.type:
            return self.type in COLLECTION_TYPES
        return any(COLLECTION_WORDS & set(normalise(t).split()) for t in self.titles)


@dataclass
class ChildWork:
    """A work created from contents entries that matched no existing work."""

    id: str
    title: str
    type: str
    type_stated: bool
    authors: list[str]
    groups: set[str]  # origin groups that list it
    record_ids: set[int]  # the parents' records that list it
    priority: int
    anchor: str


class Links(list):
    """``[(parent_id, child_id, position)]`` plus ``created``: the new child works."""

    def __init__(self, edges=(), created: list[ChildWork] | None = None) -> None:
        super().__init__(edges)
        self.created: list[ChildWork] = created or []


# The parts of an entry that merge across spellings; each has a ``_<part>_rank`` on ``_Entry``.
_PARTS = ("title", "type", "position", "authors")


@dataclass
class _Entry:
    """One child of one parent: the entries of every source that lists it."""

    key: str
    title: str = ""
    type: str | None = None
    position: float | None = None
    authors: list[str] = field(default_factory=list)
    groups: set[str] = field(default_factory=set)
    record_ids: set[int] = field(default_factory=set)
    priority: int = _DEFAULT_PRIORITY
    # (priority, source) of the claim that set each part
    _title_rank: tuple = (99, "")
    _type_rank: tuple = (99, "")
    _position_rank: tuple = (99, "")
    _authors_rank: tuple = (99, "")

    def add(self, value: dict, source: str, group: str, priority: int, record_id: int) -> None:
        rank = (priority, source)
        self.groups.add(group)
        self.record_ids.add(record_id)
        self.priority = min(self.priority, priority)
        title = str(value.get("title") or "").strip()
        if title and (rank, title) < (self._title_rank, self.title):
            self.title, self._title_rank = title, rank
        if value.get("type") and (rank, value["type"]) < (self._type_rank, self.type or ""):
            self.type, self._type_rank = value["type"], rank
        pos = value.get("position")
        numeric = isinstance(pos, (int, float)) and not isinstance(pos, bool)
        if numeric and (rank, float(cast(float, pos))) < (
            self._position_rank,
            self.position or 0.0,
        ):
            self.position, self._position_rank = float(cast(float, pos)), rank
        names = [uninvert(str(n)) for n in value.get("authors") or [] if str(n).strip()]
        if names and (rank, names) < (self._authors_rank, self.authors):
            self.authors, self._authors_rank = names, rank

    @property
    def collection(self) -> bool:
        if self.type:
            return self.type in COLLECTION_TYPES
        return bool(COLLECTION_WORDS & set(normalise(self.title).split()))


def _source(name: str, sources: Mapping[str, SourceInfo]) -> tuple[str, int]:
    info = sources.get(name)
    return (info.origin_group, info.priority) if info else (name, _DEFAULT_PRIORITY)


def _entries(work: WorkCluster, claims: Mapping[int, list[ClaimRow]], sources) -> list[_Entry]:
    """The parent's contents, merged across sources by title, in a content-derived order."""
    by_key: dict[str, _Entry] = {}
    for rid in sorted(work.record_ids):
        for c in claims.get(rid, ()):
            if c.field != "contents" or not isinstance(c.value, dict):
                continue
            title = str(c.value.get("title") or "").strip()
            key = title_key(title) if title else ""
            if not key:
                continue
            group, priority = _source(c.source, sources)
            by_key.setdefault(key, _Entry(key)).add(c.value, c.source, group, priority, rid)
    # spellings of one title (decoration, possessives, padding) are one entry
    ordered = sorted(by_key.values(), key=lambda e: (e.priority, e.key))
    merged: list[_Entry] = []
    for entry in ordered:
        home = next((m for m in merged if key_agreement(m.key, entry.key) >= TITLE_AGREEMENT), None)
        if home is None:
            merged.append(entry)
            continue
        for part in _PARTS:
            rank = getattr(entry, f"_{part}_rank")
            if getattr(entry, part) not in (None, "", []) and rank < getattr(home, f"_{part}_rank"):
                setattr(home, part, getattr(entry, part))
                setattr(home, f"_{part}_rank", rank)
        home.groups |= entry.groups
        home.record_ids |= entry.record_ids
        home.priority = min(home.priority, entry.priority)
    return merged


def child_key(title: str) -> str:
    """The key one created child is known by: its ``title_key`` without padding words
    (articles, "book", "part", "warhammer"...), so "The Last Stand" and "Last Stand" under two
    parents are one story. A title of padding words only keeps them all."""
    key = title_key(title)
    return " ".join(w for w in key.split() if w not in PADDING) or key


def _tokens(title: str) -> list[str]:
    return normalise(undecorate(title)).split()


class _Index:
    """Works by significant title token (every title agreeing at 0.9 with another shares one)
    and, for titles made only of padding words, by their exact folded form."""

    def __init__(self, info: Mapping[int, WorkInfo]) -> None:
        self.by_token: dict[str, set[int]] = defaultdict(set)
        self.by_exact: dict[str, set[int]] = defaultdict(set)
        for idx, w in info.items():
            for t in w.titles:
                toks = _tokens(t)
                sig = [x for x in toks if x not in BOILERPLATE]
                for x in sig:
                    self.by_token[x].add(idx)
                if not sig:
                    self.by_exact[" ".join(toks)].add(idx)

    def candidates(self, title: str) -> set[int]:
        toks = _tokens(title)
        out: set[int] = set(self.by_exact.get(" ".join(toks), ()))
        for x in toks:
            if x not in BOILERPLATE:
                out |= self.by_token.get(x, set())
        return out


def _compatible(entry: _Entry, work: WorkInfo) -> bool:
    """The omnibus-trap guard (as ``works._compatible``)."""
    if entry.collection == work.collection:
        return True
    if entry.type and work.type:
        return False
    exact = {normalise(t) for t in work.titles}
    return normalise(entry.title) in exact


def link(
    conn: sqlite3.Connection,
    works: Sequence[WorkCluster],
    work_ids: Mapping[int, str],
    *,
    claims: Mapping[int, list[ClaimRow]],
    sources: Mapping[str, SourceInfo],
    info: Mapping[int, WorkInfo],
) -> Links:
    """Contents edges ``[(parent_id, child_id, position)]``, sorted by parent, then position
    (unpositioned last), then child. ``Links.created`` lists the child works made for entries
    that matched no work; their IDs are assigned here (anchor ``contents``: ``child_key`` of the
    title and the first author's surname). ``works``/``work_ids``/``info`` are keyed by work index; works
    absent from ``work_ids`` are skipped."""
    index = _Index({i: info[i] for i in work_ids})
    agree = lru_cache(maxsize=None)(agreement)
    authors_agree = lru_cache(maxsize=None)(
        lambda a, b: author_agreement(list(a), list(b)) >= AUTHOR_AGREEMENT
    )

    # (priority, parent stable, position key, child stable, parent id, child id, position)
    proposals: list[tuple] = []
    created: dict[str, ChildWork] = {}
    matched: dict[str, str] = {}  # contents anchor of a matched entry -> the work it matched
    for p_idx in sorted(work_ids, key=lambda i: info[i].stable):
        parent = info[p_idx]
        for entry in _entries(works[p_idx], claims, sources):
            effective = tuple(entry.authors or parent.authors)
            match = None
            if effective:
                context = tuple(sorted({w for a in effective for w in normalise(a).split()}))
                best = None
                for cand in index.candidates(entry.title):
                    if cand == p_idx:
                        continue  # never the parent itself
                    w = info[cand]
                    if not w.authors or not authors_agree(effective, tuple(w.authors)):
                        continue
                    if not _compatible(entry, w):
                        continue
                    score = max(agree(entry.title, t, context) for t in w.titles)
                    if score >= TITLE_AGREEMENT:
                        rank = (-score, w.stable)
                        if best is None or rank < best[0]:
                            best = (rank, cand)
                match = best[1] if best else None
            authors = entry.authors or (parent.authors if len(parent.authors) == 1 else [])
            surname = normalise(authors[0]).split()[-1:] if authors else []
            anchor = f"{child_key(entry.title)}|{' '.join(surname)}"
            if match is not None:
                known_child, child_stable = work_ids[match], info[match].stable
                matched.setdefault(anchor, work_ids[match])
            else:
                child = created.get(anchor)
                if child is None:
                    child = created[anchor] = ChildWork(
                        id="", title=entry.title, type=entry.type or DEFAULT_TYPE,
                        type_stated=bool(entry.type), authors=list(authors), groups=set(),
                        record_ids=set(), priority=entry.priority, anchor=anchor,
                    )  # fmt: skip
                elif entry.priority < child.priority:
                    child.title, child.priority = entry.title, entry.priority
                    if entry.type:
                        child.type, child.type_stated = entry.type, True
                    if entry.authors:
                        child.authors = list(entry.authors)
                child.groups |= entry.groups
                child.record_ids |= entry.record_ids
                known_child, child_stable = None, f"contents:{anchor}"
            pos = entry.position
            proposals.append(
                (entry.priority, parent.stable, (pos is None, pos or 0.0), child_stable,
                 work_ids[p_idx], known_child, pos)
            )  # fmt: skip

    children = [created[a] for a in sorted(created)]
    child_ids = ids.assign_anchored(
        conn, "work", [[("contents", c.anchor)] for c in children], taken=set(work_ids.values())
    )
    id_of = {}
    for child, cid in zip(children, child_ids, strict=True):
        child.id = cid
        id_of[f"contents:{child.anchor}"] = cid
    resolved_children = {**matched, **{c.anchor: c.id for c in children}}
    _alias_former_children(conn, resolved_children, set(work_ids.values()) | set(child_ids))

    adjacency: dict[str, set[str]] = defaultdict(set)
    seen: set[tuple[str, str]] = set()
    edges = []
    for _prio, _pstable, _pkey, c_stable, parent_id, known_child, pos in sorted(
        proposals, key=lambda p: p[:4]
    ):
        child_id = known_child if known_child is not None else id_of[c_stable]
        if parent_id == child_id or (parent_id, child_id) in seen:
            continue
        if _reaches(adjacency, child_id, parent_id):
            continue  # this edge would close a cycle
        seen.add((parent_id, child_id))
        adjacency[parent_id].add(child_id)
        edges.append((parent_id, child_id, _position(pos)))
    edges.sort(key=lambda e: (e[0], e[2] is None, e[2] or 0, e[1]))
    return Links(edges, children)


def _alias_former_children(
    conn: sqlite3.Connection, matched: Mapping[str, str], live: set[str]
) -> None:
    """A story once created from contents entries that now match a real work (its own page
    arrived) keeps answering: its old ID becomes an alias of that work. An authorless child
    whose attribution became known may also join a uniquely identified live child with the
    same title; differing authors and ambiguous same-title children stay apart."""
    if not matched:
        return
    target: str | None
    attributed: dict[str, set[str]] = defaultdict(set)
    for anchor, target in matched.items():
        title, _, surname = anchor.rpartition("|")
        if surname and target in live:
            attributed[title].add(target)
    rows = []
    for anchor, id_ in conn.execute(
        "SELECT anchor_value, id FROM id_anchor WHERE entity='work' AND anchor_kind='contents'"
    ):
        target = matched.get(anchor)
        if target is None and anchor.endswith("|"):
            candidates = attributed.get(anchor[:-1], set())
            if len(candidates) == 1:
                target = next(iter(candidates))
        if target is not None and id_ not in live and id_ != target:
            rows.append((id_, target))
    conn.executemany("INSERT OR REPLACE INTO id_alias (old_id, new_id) VALUES (?, ?)", sorted(rows))


def _position(pos: float | None) -> int | float | None:
    if pos is None:
        return None
    return int(pos) if float(pos).is_integer() else pos


def _reaches(adjacency: Mapping[str, set[str]], start: str, goal: str) -> bool:
    stack, seen = [start], {start}
    while stack:
        node = stack.pop()
        if node == goal:
            return True
        for nxt in adjacency.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False
