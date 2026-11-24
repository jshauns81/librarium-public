"""Work clustering (spec 5.3 step 3): edition clusters join into works.

First by shared work identifiers, then by title + author agreement. Every union, of either
kind, passes the omnibus-trap guard: an omnibus/anthology never merges with a single work, and
a work never merges with a collection that lists it among its contents.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import combinations
from typing import cast

from bl_catalog.names import (
    BOILERPLATE,
    agreement,
    author_agreement,
    normalise,
    record_context,
    undecorate,
    uninvert,
)
from bl_catalog.resolve.editions import EditionCluster
from bl_catalog.sources.lexicanum import WIKIS, parse_page

# work_id kinds that identify a work; other kinds are kept in work_keys but never joined on
WORK_ID_KINDS = frozenset({"lexicanum", "wikidata", "hardcover", "openlibrary_work"})
TITLE_AGREEMENT = 0.9
AUTHOR_AGREEMENT = 0.6
COLLECTION_TYPES = frozenset({"omnibus", "anthology"})
# Boilerplate words that say "several works in one": agreement treats them as padding, so an
# untyped "The Soul Drinker Omnibus" would otherwise agree with "Soul Drinker".
COLLECTION_WORDS = frozenset({"omnibus", "anthology", "collection"})
AUTHOR_ROLES = frozenset({"author", "editor"})
_ANY_TITLE = "*"  # bucket token for titles made only of boilerplate words


@dataclass
class WorkCluster:
    edition_idx: set[int] = field(default_factory=set)
    record_ids: set[int] = field(default_factory=set)
    work_keys: set[str] = field(default_factory=set)
    redirect_keys: dict[int, str] = field(default_factory=dict)  # record -> redirect's source page
    redirect_titles: set[str] = field(default_factory=set)  # both explicitly equivalent spellings


@dataclass
class _Facts:
    """What the evidence of one cluster says about the work, for matching and the guard."""

    titles: set[str] = field(default_factory=set)
    authors: set[str] = field(default_factory=set)  # "First Last", authors and editors
    series: set[str] = field(default_factory=set)
    contents: set[str] = field(default_factory=set)  # titles listed as contained
    types: set[str] = field(default_factory=set)
    work_keys: set[str] = field(default_factory=set)
    redirect_keys: dict[int, str] = field(default_factory=dict)
    redirect_titles: set[str] = field(default_factory=set)

    def merge(self, other: _Facts) -> None:
        self.titles |= other.titles
        self.authors |= other.authors
        self.series |= other.series
        self.contents |= other.contents
        self.types |= other.types
        self.work_keys |= other.work_keys
        self.redirect_keys.update(other.redirect_keys)
        self.redirect_titles.update(other.redirect_titles)

    @property
    def context(self) -> frozenset[str]:
        """Words that may pad this cluster's titles: its series and author names."""
        words = record_context(None, sorted(self.authors))
        for series in self.series:
            words |= record_context(series, [])
        return frozenset(words)

    @property
    def collection(self) -> bool:
        """An omnibus/anthology: any record says so (conflicting types count as a collection,
        to keep a wrong type from merging it with a novel), or no record states a type and a
        title carries a collection word."""
        if self.types:
            return bool(self.types & COLLECTION_TYPES)
        return any(COLLECTION_WORDS & set(normalise(t).split()) for t in self.titles)


def _load_facts(conn: sqlite3.Connection, editions: list[EditionCluster]) -> list[_Facts]:
    edition_of = {rid: i for i, ed in enumerate(editions) for rid in ed.record_ids}
    facts = [_Facts() for _ in editions]
    for rid, fld, value, norm in conn.execute(
        "SELECT record_id, field, value, value_norm FROM claim"
        " WHERE field IN ('title', 'author', 'series', 'contents', 'type', 'work_id')"
    ):
        idx = edition_of.get(rid)
        if idx is None:
            continue  # not current evidence
        f = facts[idx]
        if fld == "type":
            f.types.add(norm)
        elif fld == "work_id":
            f.work_keys.add(norm)
        else:
            data = json.loads(value)
            if fld == "title":
                f.titles.add(data)
            elif fld == "author":
                name, role = data[0], data[1]  # [name, role, credit]
                if role in AUTHOR_ROLES:
                    f.authors.add(uninvert(name))
            elif fld == "series":
                f.series.add(data[0])
            elif data.get("title"):  # contents
                f.contents.add(data["title"])
    # Older redirect records claim only their target page. Also hold the explicitly named
    # source page, so a series link to that old name joins the target without an author match.
    for rid, native_id, raw, target_key, alias_norm in conn.execute(
        "SELECT r.id, r.native_id, r.parsed_json, target.value_norm, alias.value_norm"
        " FROM source_record r JOIN claim target ON target.record_id=r.id"
        " JOIN claim alias ON alias.record_id=r.id"
        " WHERE r.source='lexicanum' AND target.entity='work' AND target.field='work_id'"
        " AND alias.entity='work' AND alias.field='alias'"
    ):
        idx = edition_of.get(rid)
        if idx is not None and (key := _redirect_key(native_id, raw, target_key, alias_norm)):
            facts[idx].work_keys.add(key)
            facts[idx].redirect_keys[rid] = key
            for page_key in (key, target_key):
                page = page_key.split(":", 2)[2]
                facts[idx].redirect_titles.add(_PAGE_SUFFIX.sub("", page))
    return facts


def _redirect_key(native_id: str, raw: str, target_key: str, alias_norm: str) -> str | None:
    """The other page key of a validated, explicit same-wiki book redirect.

    Reuse the importer's redirect rules, including matching book types. Ordinary aliases,
    page metadata, and stale records cannot supply an identity bridge.
    """
    try:
        data = json.loads(raw)
    except TypeError, ValueError:
        return None
    if not isinstance(data, dict):
        return None
    wiki, page, target = (data.get(k) for k in ("wiki", "redirect", "target"))
    if not all(isinstance(v, str) and v for v in (wiki, page, target)) or wiki not in WIKIS:
        return None
    if native_id != f"{wiki}:{page}" or target_key != f"lexicanum:{wiki}:{target}":
        return None
    redirects = parse_page(wiki, cast(str, page), f"#REDIRECT [[{target}]]")
    if not redirects or redirects[0].work_ids.get("lexicanum") != f"{wiki}:{target}":
        return None
    if alias_norm not in {normalise(alias) for alias in redirects[0].aliases}:
        return None
    return f"lexicanum:{native_id}"


def cluster_works(conn: sqlite3.Connection, editions: list[EditionCluster]) -> list[WorkCluster]:
    """Group edition clusters (indexes into ``editions``) into works.

    1. Union on shared work ids (``WORK_ID_KINDS``), including both pages of an explicit
       same-type Lexicanum redirect, keys and members in sorted order.
    2. Union on title + author: ``agreement >= 0.9`` with the record context (series and
       author words) of both sides and ``author_agreement >= 0.6``. Candidate pairs come from
       buckets keyed by (author name token, title token), never from all pairs; matches are
       applied strongest first, then by the clusters' smallest edition keys, so the result
       depends on the evidence alone, not on the order it was stored in.

    Both steps refuse a union the omnibus-trap guard rejects (``_compatible``); step 2 also
    refuses to unite two different Lexicanum pages of one wiki (``_distinct_pages``). Works are
    ordered by their smallest edition index.
    """
    facts = _load_facts(conn, editions)
    agree = lru_cache(maxsize=None)(agreement)  # per run: titles and contexts repeat a lot
    authors_agree = lru_cache(maxsize=None)(
        lambda a, b: author_agreement(list(a), list(b)) >= AUTHOR_AGREEMENT
    )
    root_facts = {i: _Facts() for i in range(len(editions))}
    for i, f in enumerate(facts):
        root_facts[i].merge(f)
    parent = list(range(len(editions)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int, by_title: bool = False) -> None:
        ra, rb = find(a), find(b)
        if ra == rb or not _compatible(root_facts[ra], root_facts[rb], agree):
            return
        if by_title and _distinct_pages(root_facts[ra], root_facts[rb]):
            return
        keep, gone = min(ra, rb), max(ra, rb)
        parent[gone] = keep
        root_facts[keep].merge(root_facts.pop(gone))

    # When the guard refuses a union, which of two competing unions happens first decides the
    # outcome, so unions run in an order fixed by content, never by record ids or list
    # positions (those follow insertion order). An edition cluster's smallest key is unique to
    # it and depends only on the evidence.
    stable = [min(ed.keys) for ed in editions]

    # 1. shared work identifiers
    by_key: dict[str, list[int]] = defaultdict(list)
    for i, f in enumerate(facts):
        for key in f.work_keys:
            kind = key.split(":", 1)[0]
            if kind in WORK_ID_KINDS:
                # Lexicanum page titles differing only in case are one book filed twice
                by_key[key.casefold() if kind == "lexicanum" else key].append(i)
    for key in sorted(by_key):
        first, *rest = sorted(by_key[key], key=stable.__getitem__)
        for i in rest:
            union(first, i)

    # 2. title + author, within buckets
    contexts = [f.context for f in facts]
    matches: list[tuple[float, str, str, int, int]] = []
    for i, j in _candidate_pairs(facts):
        context = tuple(sorted(contexts[i] | contexts[j]))
        score = _title_author_score(facts[i], facts[j], context, agree, authors_agree)
        if score:
            matches.append(
                cast(
                    tuple[float, str, str, int, int],
                    (-score, *sorted((stable[i], stable[j])), i, j),
                )
            )
    for *_, i, j in sorted(matches):
        union(i, j, by_title=True)

    works: dict[int, WorkCluster] = {}
    for i, ed in enumerate(editions):
        work = works.setdefault(find(i), WorkCluster())
        work.edition_idx.add(i)
        work.record_ids |= ed.record_ids
        work.work_keys |= facts[i].work_keys
        work.redirect_keys.update(facts[i].redirect_keys)
        work.redirect_titles.update(facts[i].redirect_titles)
    return sorted(works.values(), key=lambda w: min(w.edition_idx))


def _title_tokens(title: str) -> list[str]:
    return normalise(undecorate(title)).split()


def _candidate_pairs(facts: list[_Facts]) -> list[tuple[int, int]]:
    """Pairs that share an author name token and a title token.

    Title agreement >= 0.9 means one title's tokens run inside the other's, and every way
    author_agreement reaches 0.6 needs a shared name word, so bucketing on (name token,
    non-boilerplate title token) loses no match. A title made only of boilerplate words has no
    such token; it is compared with everything that shares a name token.
    """
    buckets: dict[tuple[str, str], list[int]] = defaultdict(list)
    by_name: dict[str, list[int]] = defaultdict(list)
    wildcard: dict[str, list[int]] = defaultdict(list)
    for i, f in enumerate(facts):
        if not f.titles or not f.authors:
            continue
        names = {tok for a in f.authors for tok in normalise(a).split()}
        title_toks: set[str] = set()
        any_title = False
        for t in f.titles:
            toks = [tok for tok in _title_tokens(t) if tok not in BOILERPLATE]
            title_toks |= set(toks)
            any_title |= not toks
        for name in names:
            by_name[name].append(i)
            if any_title:
                wildcard[name].append(i)
            for tok in title_toks:
                buckets[(name, tok)].append(i)
    pairs: set[tuple[int, int]] = set()
    for members in buckets.values():
        pairs.update(combinations(members, 2))  # members are in ascending order
    for name, members in wildcard.items():
        for i in members:
            pairs.update((min(i, j), max(i, j)) for j in by_name[name] if j != i)
    return sorted(pairs)


def _title_author_score(a: _Facts, b: _Facts, context, agree, authors_agree) -> float:
    """Best title agreement (padding allowed from ``context``, the series and author words of
    both sides) when it reaches the bar and the authors agree, else 0."""
    if not authors_agree(tuple(sorted(a.authors)), tuple(sorted(b.authors))):
        return 0.0
    best = max(agree(x, y, context) for x in sorted(a.titles) for y in sorted(b.titles))
    return best if best >= TITLE_AGREEMENT else 0.0


def _compatible(a: _Facts, b: _Facts, agree) -> bool:
    """The omnibus-trap guard: may these two clusters be one work?"""
    if a.collection != b.collection:
        single = b if a.collection else a
        whole = a if a.collection else b
        if single.types:
            return False  # a typed novel/story/... never merges with an omnibus/anthology
        # Untyped: one of its own titles must *be* the collection's title, word for word with
        # its decoration. Padding agreement (0.9) is how "Soul Drinker" meets "The Soul Drinker
        # Omnibus", and agreement's undecorate makes "Soul Drinker (Omnibus)" a 1.0 match.
        if single.titles and not (_exact(single.titles) & _exact(whole.titles)):
            return False
    return not (_listed_in(a, b, agree) or _listed_in(b, a, agree))


_PAGE_SUFFIX = re.compile(r"\s*\([^()\d]*\)\s*$")  # "(Novel)", never a year "(2017/18)"


def _pages(f: _Facts) -> dict[str, set[str]]:
    """``{wiki: {page title minus suffix, casefolded}}`` of the cluster's Lexicanum pages."""
    out: dict[str, set[str]] = defaultdict(set)
    for key in f.work_keys:
        kind, _, rest = key.partition(":")
        wiki, _, page = rest.partition(":")
        if kind == "lexicanum" and page:
            out[wiki].add(_PAGE_SUFFIX.sub("", page).casefold())
    return out


def _distinct_pages(a: _Facts, b: _Facts) -> bool:
    """Do the clusters hold different book pages of one wiki? Two pages are two books (a title
    match never unites them), unless their titles differ only in case or suffix: one book
    filed twice ("Blades Of Damocles", "Blades of Damocles (Novel)")."""
    pa, pb = _pages(a), _pages(b)
    return any(pa[w] and pb[w] and not pa[w] & pb[w] for w in pa.keys() & pb.keys())


def _exact(titles: set[str]) -> set[str]:
    """Titles compared word for word, decoration included ("Soul Drinker (Omnibus)" stays
    "soul drinker omnibus"): the guard's notion of "the same title"."""
    return {normalise(t) for t in titles}


def _listed_in(item: _Facts, whole: _Facts, agree) -> bool:
    """Does one of ``item``'s titles appear among ``whole``'s contents?

    Only a single work can be one of the contents: a collection's own title agrees with its
    first entry through padding alone ("The Soul Drinker Omnibus" / "Soul Drinker"), which must
    not keep two records of that collection apart. A contents entry with the collection's own
    title (an anthology named after one of its stories) is skipped too, for the same reason.
    """
    if item.collection:
        return False
    own = _exact(whole.titles)
    listed = [c for c in sorted(whole.contents) if normalise(c) not in own]
    return any(agree(t, c, ()) >= TITLE_AGREEMENT for t in sorted(item.titles) for c in listed)
