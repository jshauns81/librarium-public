"""Near-equality of titles and person names, shared by edition clustering and field voting.

Stricter than ``names.agreement``, which is tuned for finding a work at all: its padding
vocabulary (BOILERPLATE) includes series words ("space marine", "battles") and the collection
words, so "Space Marine" ~ "Space Marine Battles" and "Soul Drinker" ~ "Soul Drinker Omnibus"
both score 0.9. Here only articles, format words and the record's own series and author words
may pad a title, and a collection never equals a single work.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from bl_catalog.names import agreement, normalise, undecorate, uninvert
from bl_catalog.resolve import people

# Words that may pad a title without changing which book it is.
PADDING = frozenset(
    ["the", "a", "an", "of", "and", "novel", "novella", "book", "volume", "vol", "part",
     "edition", "warhammer", "40", "000", "40k", "30k", "black", "library", "games",
     "workshop", "series"]
)  # fmt: skip
COLLECTION_WORDS = frozenset({"omnibus", "anthology", "collection"})
MATCH = 0.9  # the agreement two titles need to be one
LOOSE = 0.5  # below this ``names.agreement``, two titles on one edition key are different works

# Edition decorations ``names.DECORATION`` leaves alone: audiobook and print-run qualifiers.
_EDITION_DECORATION = re.compile(
    r"\s*[(\[][^()\[\]]*\b(?:unabridged|abridged|audiobook|audio\s+edition|large\s+print|"
    r"dramati[sz]ed)\b[^()\[\]]*[)\]]\s*$",
    re.IGNORECASE,
)
_POSSESSIVE = re.compile(r"(?<=\w)['’](?=s\b)")
_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8",
    "ix": "9", "x": "10", "xi": "11", "xii": "12",
}  # fmt: skip
_VOLUME_WORDS = frozenset({"book", "volume", "vol", "part", "no", "number"})


def strip_edition_decoration(title: str) -> str:
    """'Horus Rising (Unabridged)' -> 'Horus Rising'; nothing else is touched."""
    previous = None
    while previous != title:
        previous = title
        title = _EDITION_DECORATION.sub("", title).strip()
    return title


def undecorated(title: str) -> str:
    """The title without catalogue or edition decoration (the spelling to display)."""
    previous = None
    while previous != title:
        previous = title
        title = undecorate(strip_edition_decoration(title))
    return title


def fold_possessive(text: str) -> str:
    """ "Gaunt's Ghosts" -> "Gaunts Ghosts", so it meets the apostrophe-less spelling."""
    return _POSSESSIVE.sub("", text)


def title_key(title: str) -> str:
    """The compared form of a title: undecorated, possessives folded, normalised. A collection
    word only the decoration carried is kept ("Soul Drinker (Omnibus)" -> "soul drinker
    omnibus"), so a key says whether its title is a collection."""
    key = normalise(fold_possessive(undecorated(title)))
    words = COLLECTION_WORDS & set(normalise(title).split())
    if words and not words & set(key.split()):
        key = f"{key} {min(words)}".strip()
    return key


def is_collection(title: str) -> bool:
    """A title that says several works in one, decoration included."""
    return bool(COLLECTION_WORDS & set(normalise(title).split()))


def context_words(series: Iterable[str] = (), authors: Iterable[str] = ()) -> frozenset[str]:
    """Words that may pad a title of this work: its series and author names."""
    words: set[str] = set()
    for name in series:
        words |= set(title_key(name).split())
    for name in authors:
        words |= set(normalise(uninvert(name)).split())
    return frozenset(words)


def title_agreement(a: str, b: str, context: Iterable[str] = ()) -> float:
    """1.0 for the same key, 0.9 when one title runs inside the other and every extra word is
    padding (``PADDING`` or ``context``), else 0. A collection never agrees with a non-
    collection, whatever the words."""
    return key_agreement(title_key(a), title_key(b), context)


def key_agreement(a: str, b: str, context: Iterable[str] = ()) -> float:
    """``title_agreement`` on precomputed ``title_key``s."""
    ta, tb = a.split(), b.split()
    if bool(COLLECTION_WORDS & set(ta)) != bool(COLLECTION_WORDS & set(tb)):
        return 0.0
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    allowed = PADDING | set(context)
    for start in range(len(long) - len(short) + 1):
        if long[start : start + len(short)] == short:
            extra = long[:start] + long[start + len(short) :]
            if all(word in allowed for word in extra):
                return MATCH
    return 0.0


def same_person(a: str, b: str) -> bool:
    """The same person, spelled two ways: equal after un-inverting and normalising, or the same
    surname with compatible given names, where an initial matches a name it begins
    ("W. King" ~ "William King") or a short form and the name it shortens ("Josh" ~ "Joshua"; see
    ``people``). "Dan Abnett" and "Nik Vincent-Abnett" are not the same."""
    return people.same_person(a, b)


def key_compatibility(a: str, b: str, context: Iterable[str] = ()) -> float:
    """How well two ``title_key``s fit one edition key (ISBN/ASIN), leniently: 0.0 only for
    clearly different works. Catalogue feeds truncate and decorate titles ("Seeds" for "The
    Seeds of Heresy", "Horus Rising" for "Horus Rising: The Seeds of Heresy Are Sown"), and
    splitting on those would scatter one book into single-source strays.

    0.0 when the collection guard separates them (an omnibus never shares a key with a single
    work), when both give a different volume number ("Book 1" / "Book 2"), or when all of these hold: neither side's significant words (``_significant``) are a
    subset or a prefix of the other's, and ``names.agreement`` with ``context`` is below
    ``LOOSE``. Otherwise the best of ``key_agreement``, ``names.agreement`` and ``LOOSE``, so the
    strict match still ranks first when a title fits several families.
    """
    ta, tb = a.split(), b.split()
    if bool(COLLECTION_WORDS & set(ta)) != bool(COLLECTION_WORDS & set(tb)):
        return 0.0
    if not ta or not tb:
        return 0.0
    (_, na), (_, nb) = _volume(ta), _volume(tb)
    if na and nb and na != nb:
        return 0.0  # "Eisenhorn Book 1" and "Eisenhorn Book 2" are different books
    words = frozenset(context)
    score = max(key_agreement(a, b, words), agreement(a, b, words))
    if score >= LOOSE:
        return score
    sa, sb = _significant(ta, tb, words)
    if _contained(sa, sb) or _contained(sb, sa):
        return LOOSE
    return 0.0


def _significant(ta: list[str], tb: list[str], context: frozenset[str]) -> tuple[list, list]:
    """Both titles' words that name the book: without padding, series and author words, and a
    "Book N" volume number. The numbers stay when both sides give one and they differ, so
    "Eisenhorn Book 1" never fits "Eisenhorn Book 2". A title that is all padding keeps its
    words, so it cannot fit everything."""
    (wa, na), (wb, nb) = _volume(ta), _volume(tb)
    if na and nb and na != nb:
        wa, wb = wa + sorted(na), wb + sorted(nb)
    dropped = PADDING | context

    def keep(words: list[str]) -> list[str]:
        return [w for w in words if w not in dropped] or words

    return keep(wa), keep(wb)


def _volume(words: list[str]) -> tuple[list[str], set[str]]:
    """The words without "book 1" / "volume two" / "part iv", and the numbers removed."""
    out: list[str] = []
    numbers: set[str] = set()
    i = 0
    while i < len(words):
        word, nxt = words[i], words[i + 1] if i + 1 < len(words) else ""
        number = nxt if nxt.isdigit() else _NUMBER_WORDS.get(nxt)
        if word in _VOLUME_WORDS and number:
            numbers.add(str(int(number)))
            i += 2
            continue
        out.append(word)
        i += 1
    return out, numbers


def _contained(short: list[str], long: list[str]) -> bool:
    """``short``'s words are a subset of ``long``'s, or ``short`` is ``long`` cut off part-way
    through a word ("the seeds of her"), which needs at least two words."""
    if set(short) <= set(long):
        return True
    n = len(short)
    return 2 <= n <= len(long) and short[:-1] == long[: n - 1] and long[n - 1].startswith(short[-1])
