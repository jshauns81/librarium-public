"""ISBN validation, normalisation, and extraction utilities.

Pure Python: checksums are computed here rather than delegated to a library.
"""

from __future__ import annotations

import re

# Matches hyphenated or plain 10/13-digit ISBNs embedded in text. The digit
# lookarounds stop a match starting or ending inside a longer number, and the
# ISBN-13 alternative is tried first at each position.
# Between digit groups there may be nothing, or one or two hyphens/spaces in any mix
# (``978- 1 78496 992 9``).
_SEP = r"[-\s]{0,2}"
_ISBN_RAW = re.compile(
    rf"(?<![\d-])(?:97[89](?:{_SEP}\d){{10}}"  # ISBN-13 with optional hyphens/spaces
    rf"|\d(?:{_SEP}\d){{8}}{_SEP}[\dXx])(?!\d)"  # ISBN-10 with optional hyphens/spaces
)

# A leading "ISBN", "ISBN-10:", "ISBN 13" etc. label; its digits are not ISBN digits.
# The 10/13 counts as part of the label only when a non-digit follows it, so the
# leading digits of an unhyphenated ISBN-10 ("ISBN 1316000001") are not eaten.
_LABEL = re.compile(r"^\s*ISBN(?:[-\s]?(?:10|13)(?=\D))?\s*:?", re.IGNORECASE)


def strip_isbn_label(raw: str) -> str:
    """Remove a leading ``ISBN``/``ISBN-10:``/``ISBN-13:`` label, leaving the rest as given."""
    return _LABEL.sub("", raw)


def _valid10(code: str) -> bool:
    if not re.fullmatch(r"\d{9}[\dX]", code):
        return False
    total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(code))
    return total % 11 == 0


def _check13(first12: str) -> str:
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(first12))
    return str((10 - total % 10) % 10)


def is_valid13(s: str) -> bool:
    """True for a valid ISBN-13 (hyphens and spaces allowed)."""
    code = re.sub(r"[-\s]", "", s)
    return bool(re.fullmatch(r"\d{13}", code)) and _check13(code[:12]) == code[12]


def to_isbn13(raw: str) -> str | None:
    """Normalise a valid ISBN-10 or ISBN-13 to bare ISBN-13, else None.

    Hyphens, spaces and an ``ISBN``/``ISBN-10:``/``ISBN-13:`` label are ignored.
    """
    cleaned = re.sub(r"[^\dXx]", "", strip_isbn_label(raw)).upper()
    if len(cleaned) == 10:
        if not _valid10(cleaned):
            return None
        body = "978" + cleaned[:9]
        return body + _check13(body)
    if len(cleaned) == 13 and is_valid13(cleaned):
        return cleaned
    return None


def isbn10_of(isbn13: str) -> str | None:
    """ISBN-10 of an ISBN-13 (only exists for the 978 prefix), else None."""
    code = re.sub(r"[-\s]", "", isbn13)
    if not is_valid13(code) or not code.startswith("978"):
        return None
    body = code[3:12]
    total = sum((10 - i) * int(c) for i, c in enumerate(body))
    check = (11 - total % 11) % 11
    return body + ("X" if check == 10 else str(check))


def extract_isbns(text: str) -> list[str]:
    """Extract and normalise all recognisable ISBNs from a block of text."""
    seen: dict[str, None] = {}
    pos = 0
    while m := _ISBN_RAW.search(text, pos):
        normalised = to_isbn13(m.group())
        if normalised:
            seen[normalised] = None
            pos = m.end()
        else:
            # A stray number can be joined to a real ISBN by a separator; retry
            # from the next character instead of skipping the whole candidate.
            pos = m.start() + 1
    return list(seen)
