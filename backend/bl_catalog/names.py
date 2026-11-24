"""Name matching for titles and authors, ported from magi-identity.

Copied (not imported) so bl-catalog and magi-identity deploy independently. The
docstrings document real traps that auto-applied wrong matches before these
rules existed; keep them.
"""

from __future__ import annotations

import re
import unicodedata


def normalise(value):
    """Casefolded word key, for comparing names that disagree on punctuation."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"\w+", text))


def placeholder_person(name: str) -> bool:
    """An unnamed contributor is missing evidence, not a competing person."""
    return normalise(name) in {
        "various",
        "unknown",
        "anonymous",
        "anon",
        "none",
        "n a",
        "various authors",
        "unknown author",
    }


DECORATION = re.compile(
    r"\s*(?:\((?:[^)]*\b(?:book|volume|vol|novel|omnibus|series|warhammer|"
    r"40[,.]?000|40k|30k|paperback|hardcover|kindle|ebook)\b[^)]*)\)|"
    r"\[[^\]]*\]|\bOOP\b|\s[-–—]\s*(?:Warhammer|Black Library).*)\s*$",
    re.IGNORECASE,
)


def undecorate(title):
    """Strip catalogue decoration until it stops shrinking."""
    previous = None
    while previous != title:
        previous = title
        title = DECORATION.sub("", title).strip(" .:-–—")
    return title


def agreement(left, right, context=()):
    """How strongly two names agree.

    Equality after decoration removal is agreement. Containment is agreement
    *only* when every leftover word is explained as padding — boilerplate, the
    series name, or the author's name. Unexplained leftover words mean these are
    different works, however much they overlap: 'The Hunt for Vulkan' is not
    'The Hunt', and 'Old Earth: To the Gates of Terra' is not 'The Gates of
    Terra'. Both were auto-applied before this rule existed.
    """
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    start = _subsequence(short, long)
    if start >= 0:
        extra = long[:start] + long[start + len(short) :]
        allowed = BOILERPLATE | set(context)
        return 0.9 if all(word in allowed for word in extra) else 0.0
    overlap = len(set(a) & set(b)) / max(1, len(set(a) | set(b)))
    return 0.7 if overlap >= 0.6 else 0.0


def record_context(series: str | None, authors: list[str]) -> set[str]:
    """Words that may legitimately pad this record's title."""
    words = set(normalise(series or "").split())
    for author in authors or []:
        words |= set(normalise(author).split())
    return words


# Words that can appear as padding around a title without changing which work it
# is: format, imprint and setting boilerplate. Series and author names are added
# per-record, since those are the other things rippers and cataloguers splice in.
BOILERPLATE = frozenset(
    [
        "the",
        "a",
        "an",
        "of",
        "and",
        "warhammer",
        "40",
        "000",
        "40k",
        "30k",
        "age",
        "sigmar",
        "horus",
        "heresy",
        "black",
        "library",
        "games",
        "workshop",
        "novel",
        "novella",
        "story",
        "stories",
        "omnibus",
        "anthology",
        "collection",
        "series",
        "book",
        "volume",
        "vol",
        "part",
        "edition",
        "necromunda",
        "blood",
        "angels",
        "space",
        "marine",
        "battles",
        "legends",
        "adventures",
        "horror",
        "crime",
    ]
)


def _tokens(value):
    return normalise(undecorate(value)).split()


def _subsequence(needle, haystack):
    """Index of needle as a contiguous run of whole tokens, or -1.

    Whole tokens matter: raw string containment made 'Soul Drinker' match inside
    "The Soul Drinker's Omnibus" (it is the first novel *in* that omnibus), which
    is precisely the omnibus trap this pass exists to avoid.
    """
    if not needle or len(needle) > len(haystack):
        return -1
    for start in range(len(haystack) - len(needle) + 1):
        if haystack[start : start + len(needle)] == needle:
            return start
    return -1


def author_agreement(a: list[str], b: list[str]) -> float:
    """Surnames are compared loosely: catalogue authors are inverted, padded
    ('Andy     Clark'), and padded with narrator credits."""
    best = 0.0
    for candidate in a:
        for stated in b:
            score = agreement(candidate, stated)
            if not score:
                left, right = normalise(candidate).split(), normalise(stated).split()
                if left and right and left[-1] == right[-1]:
                    score = 0.6
            best = max(best, score)
    return best


_LIFE_DATES = re.compile(r",\s*\d{4}\s*-\s*(?:\d{4})?\.?\s*$")
_CORPORATE = frozenset(
    ["ltd", "inc", "limited", "publishing", "workshop", "games", "press", "books"]
)


def uninvert(name):
    """'King, William' -> 'William King'; 'King, William, 1959-' -> 'William King'.

    Catalogues (ISBNdb, library records) list authors surname first, often with life dates.
    author_agreement's shared-surname rule compares *last* words, so an inverted name only meets
    a shortened one ('W. King') once it is turned round. Only a single "Last, First" is turned:
    a trailing life-date part is dropped first, then exactly one comma must remain. Left alone:
    two people ('Dan Abnett, Graham McNeill': both sides have a space), corporate names
    ('Games Workshop, Ltd.'), and anything with more commas ('Smith, John, Jr.', lists).
    """
    text = _LIFE_DATES.sub("", str(name or ""))
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 2 or not all(parts):
        return text if text != str(name or "") else name
    last, first = parts
    if " " in last and " " in first:
        return text
    if _CORPORATE & set(normalise(text).split()):
        return text
    return f"{first} {last}"
