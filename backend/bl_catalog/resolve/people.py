"""One person, however the sources spell them.

The vote on a work merges spellings of one person credited on that work (``same_person``). The
catalogue has to go further: "Josh Reynolds" on one work and "Joshua Reynolds" on another are
one author, and a caller matching credits needs one canonical name for him, with the other
spellings as aliases. ``cluster`` does that over every credited name at rebuild time.

Two spellings are one person when, after un-inverting, dropping a trailing disambiguator
("Wayne Reynolds (Artist)") and leading honorifics ("Mr. Josh Reynolds"), they share a surname
and their given names are compatible: equal, an initial that begins the other ("W." ~
"William"), or a short form and the name it shortens (``NICKNAMES``: "Josh" ~ "Joshua", "Andy"
~ "Andrew"). A middle name that only one side gives is ignored ("Joshua M. Reynolds" ~ "Joshua
Reynolds"); two different middle names are two people.

Merging is cautious where it could join two real people: full given names cluster by complete
linkage (every spelling in a cluster fits every other). An initial ("J. Reynolds") or a short
form with multiple formal names ("Al Smith") joins only when exactly one established cluster
of that surname fits it. These matches are decided together so one uncertain spelling cannot
disambiguate another. Lists of several people in one credit ("Guy Haley, Josh Reynolds Nick
Kyme") and corporate names never merge with anything but their own exact spelling.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping

from bl_catalog.names import normalise, uninvert

# Short forms of given names and the formal names they stand for. Only pairs that are not one
# an initial of the other: "J." ~ "Joshua" needs no entry. Multiple expansions require a
# unique cluster fit. "Chris" (Christopher, Christian, Christine) is deliberately left out.
NICKNAMES = {
    "abe": ("abraham",), "al": ("alan", "alastair", "alexander"), "alex": ("alexander",),
    "andy": ("andrew",), "ben": ("benjamin",), "bill": ("william",), "bob": ("robert",),
    "charlie": ("charles",), "dan": ("daniel",), "danny": ("daniel",), "dave": ("david",),
    "ed": ("edward", "edmund"), "fred": ("frederick",), "gav": ("gavin",), "greg": ("gregory",),
    "jim": ("james",), "jamie": ("james",), "jeff": ("jeffrey",), "joe": ("joseph",),
    "jon": ("jonathan",), "josh": ("joshua",), "ken": ("kenneth",), "larry": ("lawrence",),
    "matt": ("matthew",), "mike": ("michael",), "nick": ("nicholas",), "nik": ("nicholas",),
    "pete": ("peter",), "phil": ("philip", "phillip"), "rob": ("robert",), "robbie": ("robert",),
    "sam": ("samuel",), "steve": ("steven", "stephen"), "tim": ("timothy",), "tom": ("thomas",),
    "tony": ("anthony",), "will": ("william",),
}  # fmt: skip
_HONORIFICS = frozenset(
    {"mr", "mrs", "ms", "miss", "dr", "sir", "prof", "professor", "monsieur", "madame", "mme"}
)
_CORPORATE = frozenset(
    {"ltd", "inc", "limited", "publishing", "workshop", "games", "press", "books", "library",
     "various", "anonymous", "unknown"}
)  # fmt: skip
_DISAMBIGUATOR = re.compile(r"\s*\([^()]*\)\s*$")
_LIST = re.compile(r"[&;/+]|\band\b", re.IGNORECASE)  # "Dan & Lee Abnett", "Gav Thorpe/C Z Dunn"
_JOINED_INITIALS = re.compile(r"[^aeiouy\d]{2,3}")  # "CL Werner": no vowel, so not a name
_MAX_TOKENS = 4  # more than this in one credit is a list of people, not a name


def display_name(name: str) -> str:
    """Un-invert a catalogue name while keeping its disambiguator at the end.

    Turning ``"Lee, Mike (Writer)"`` straight round puts ``"(Writer)"`` in the middle of the
    name, where ``name_tokens`` can no longer remove it.
    """
    text = str(name or "")
    suffix = _DISAMBIGUATOR.search(text)
    if suffix is None:
        return uninvert(text)
    bare = text[: suffix.start()].strip()
    return f"{uninvert(bare)} {suffix.group().strip()}" if bare else text


def name_tokens(name: str) -> list[str]:
    """The compared words of a person's name: disambiguator dropped, un-inverted, leading
    honorifics dropped, normalised, and joined initials split ("CL Werner" -> c l werner)."""
    text = _DISAMBIGUATOR.sub("", str(name or "")) or str(name or "")
    words = normalise(uninvert(text)).split()
    while len(words) > 2 and words[0] in _HONORIFICS:
        words = words[1:]
    if len(words) < 2:
        return words
    given = [
        part for w in words[:-1] for part in (list(w) if _JOINED_INITIALS.fullmatch(w) else [w])
    ]
    return [*given, words[-1]]


def _mergeable(name: str, words: list[str]) -> bool:
    """A single person's name that may merge with other spellings: two to four words, no
    corporate word, and not a list of people."""
    return (
        2 <= len(words) <= _MAX_TOKENS
        and not (_CORPORATE & set(words))
        and not _LIST.search(name)
        # A comma is an inverted name only when uninvert can turn it round. In particular,
        # "Dan Abnett, Guy Haley" is two people even though it has just four words.
        and ("," not in name or display_name(name) != name)
    )


def single(name: str) -> bool:
    """A name that reads as one person (not a list of people, not a corporate credit)."""
    return _mergeable(name, name_tokens(name))


def _formal(word: str) -> set[str]:
    return {word, *NICKNAMES.get(word, ())}


def given_compatible(x: str, y: str) -> bool:
    """Two given names of one person: equal, an initial of the other, or one a short form of
    the other ("josh" ~ "joshua")."""
    if x == y or (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y)):
        return True
    return bool(_formal(x) & _formal(y))


def compatible(a: list[str], b: list[str]) -> bool:
    """Two token lists (``name_tokens``) that may be one person: same surname, every given name
    both sides give compatible position by position (extra middle names are ignored)."""
    if a == b:
        return bool(a)
    if len(a) < 2 or len(b) < 2 or a[-1] != b[-1]:
        return False
    return all(given_compatible(x, y) for x, y in zip(a[:-1], b[:-1], strict=False))


def same_person(a: str, b: str) -> bool:
    """Two spellings of one person (the rules above). A list of people or a corporate name is
    only ever itself, compared as normalised text."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not (_mergeable(a, ta) and _mergeable(b, tb)):
        return bool(ta) and normalise(uninvert(a)) == normalise(uninvert(b))
    return compatible(ta, tb)


def _requires_unique_fit(words: tuple[str, ...]) -> bool:
    return len(words[0]) == 1 or any(len(NICKNAMES.get(w, ())) > 1 for w in words[:-1])


def _display_rank(name: str, works: int) -> tuple:
    """Canonical spelling first: a clean name (no disambiguator, honorific, inversion or
    all-lowercase), then the most works, then given names written out, then alphabetical."""
    words = normalise(name).split()
    clean = (
        not _DISAMBIGUATOR.search(name)
        and "," not in name
        and not (words and words[0] in _HONORIFICS)
        and name != name.lower()
    )
    spelled = sum(len(w) > 1 for w in words)
    return (not clean, -works, -spelled, name)


def cluster(works: Mapping[str, int]) -> dict[str, list[str]]:
    """Group credited names into people.

    ``works`` maps each credited spelling to the number of works crediting it. Returns
    ``{canonical name: [every spelling, canonical first]}``; every input name appears in exactly
    one group.
    """
    # A key is the name's tokens; a list of people keys on its whole text, so it only ever
    # groups with its own spellings.
    by_key: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for name in works:
        words = name_tokens(name)
        key = tuple(words) if _mergeable(name, words) else ("", normalise(name))
        by_key[key].append(name)

    def weight(key: tuple[str, ...]) -> int:
        return sum(works[n] for n in by_key[key])

    groups: list[list[tuple[str, ...]]] = []  # each a list of keys
    by_surname: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for key in by_key:
        if key[0]:
            by_surname[key[-1]].append(key)
        else:
            groups.append([key])
    for keys in by_surname.values():
        keys.sort(key=lambda k: (-weight(k), k))
        clusters: list[list[tuple[str, ...]]] = []
        for key in (k for k in keys if not _requires_unique_fit(k)):
            home = next(
                (c for c in clusters if all(compatible(list(key), list(m)) for m in c)), None
            )
            if home is None:
                clusters.append([key])
            else:
                home.append(key)
        loose: list[list[tuple[str, ...]]] = []  # uncertain names that fit no single cluster
        pending: dict[int, list[tuple[str, ...]]] = defaultdict(list)
        for key in (k for k in keys if _requires_unique_fit(k)):
            # Keep established clusters unchanged while finding every uncertain name's fit.
            fits = [
                i for i, c in enumerate(clusters) if all(compatible(list(key), list(m)) for m in c)
            ]
            if len(fits) == 1:
                pending[fits[0]].append(key)
            else:
                loose.append([key])
        for i, candidates in pending.items():
            for key in candidates:
                # Missing middle names can make two conflicting spellings fit the same
                # person. Keep both loose instead of selecting whichever was processed first.
                if all(compatible(list(key), list(other)) for other in candidates):
                    clusters[i].append(key)
                else:
                    loose.append([key])
        groups.extend(clusters)
        groups.extend(loose)

    out: dict[str, list[str]] = {}
    for keys in groups:
        spellings = sorted(
            (n for k in keys for n in by_key[k]), key=lambda n: _display_rank(n, works[n])
        )
        out[spellings[0]] = spellings
    return out
