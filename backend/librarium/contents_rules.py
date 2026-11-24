"""Library Finish's lab-settled contents text rules, shared by inspection and planning.

Ported from LF 72bdf39 bin/epub_content.py:438-563,641-720,769-799,1067-1114 and 1144-1147
(KC/KCb, D086-D087; unchanged since a2a3692). The inspection uses them only to
choose which short lines to record; the planner uses them to decide. They read
labels, never book prose, and never change source bytes.
"""

import collections
import re

NUMBER_WORD = (
    r"(?:(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)[- ]?)?"
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen"
    r"|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy"
    r"|eighty|ninety|hundred)"
)
# A well-formed Roman numeral (I to MMMCMXCIX), so words such as "Mix" or "Civil" are not one.
ROMAN = r"(?=[IVXLCDM])M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})"
# A styled paragraph that is only a chapter marker: "Chapter 12", "CHAPTER TWO: The Fall".
STYLED_HEADING = re.compile(
    r"^(?i:(?:chapter|part|book)(?:\s*[:.]\s*|\s+)(?:\d+|(?-i:" + ROMAN + r")|" + NUMBER_WORD + r")"
    r"|prologue|epilogue|interlude)\b"
    r"(?:\s*$|\s*[:.–—-]\s*\S.{0,60}$|\s+[\"“‘'A-Z].{0,60}$)"
)
# The bare number in a paragraph styled as a chapter number, e.g. "One".
CHAPTER_NUMBER = re.compile(r"^(?:\d+|" + ROMAN + r"|" + NUMBER_WORD + r")$", re.IGNORECASE)
# A file opening with its chapter number and title, e.g. "1: THE SPIRE" or "XII - The Fall".
NUMBERED_TITLE = re.compile(
    r"^(?:\d+|" + ROMAN + r"|(?i:" + NUMBER_WORD + r"))\s*[:.–—-]\s*\S.{0,60}$"
)
CONTENTS_HEADING = re.compile(r"^(?:table of )?contents$", re.IGNORECASE)
NOT_A_CHAPTER = re.compile(
    r"^(?:(?:table of )?contents|backlist|also (?:available|by)\b.*"
    r"|(?:other|more) (?:great |good )?[\w ,-]{0,40}?(?:books|titles|novels|reads|stories)\b.*"
    r"|by the same author|warhammer(?: 40,?000| age of sigmar| fantasy)?"
    r"|(?:order|download|buy) the (?:full|complete) range\b.*"
    r"|.*\b(?:www\.[\w.-]+|[\w-]+\.(?:com|net|org|co\.uk))\b.*"
    r"|this licen[cs]e\b.*|e-?book licen[cs]e|licen[cs]e|copyright|a black library publication"
    r"|legal(?: notice)?"
    r"|.*\bfrom (?:the )?black library|see (?:the )?black library\b.*"
    r"|a black library (?:publication )?imprint|warhammer (?:adventures|horror)"
    r"|hammer (?:and|&) bolter)$",
    re.IGNORECASE,
)
# A copyright page, whatever its heading says: two or more of these in a short page.
PUBLISHER_PAGE = re.compile(
    r"©|\bcopyright\b|\ball rights reserved\b|\bfirst published\b|\bisbn\b"
    r"|\bbritish library cataloguing\b|\bpublished (?:in|by) [^.]{0,60}black library",
    re.IGNORECASE,
)
DEBRIS_LABEL = re.compile(r"^(?:delete me|untitled|blank page|placeholder)$", re.IGNORECASE)
# A heading that names a file or a placeholder, never a chapter.
HEADING_JUNK = re.compile(
    r"^(?:start|unknown|cover|untitled|(?:index_)?split_\d+|[\w-]+\.x?html?)$", re.IGNORECASE
)
# A contents-list label that names a file or a placeholder.
JUNK_LABEL = re.compile(
    r"^(?:|start|unknown|cover|untitled|(?:index_)?split_\d+|\d+)$", re.IGNORECASE
)
# Front and back sections: listed beside the chapters, never holding them.
SECTION_LABEL = re.compile(
    r"^(?:prologue|epilogue|interlude|afterword|foreword|introduction|preface"
    r"|acknowledge?ments?|coda)\b",
    re.IGNORECASE,
)
# Pages around the story that never title a novel in an omnibus.
BACK_MATTER = re.compile(
    r"^(?:about the authors?|a black library publication|appendix|appendices|glossary"
    r"|dramatis personae|acknowledge?ments?|illustrations|also by\b.*|see black library\b.*"
    r"|.*\bpublication|e-?book licen[cs]e)$",
    re.IGNORECASE,
)
# A story's byline: one or two people's names in title case.
NAME_WORD = (
    r"(?!(?:The|Of|A|An|In|On|At|To|For|From|By|With|And|Chapter|Part|Book)\b)"
    r"[A-Z][a-z’'-]*(?:[A-Z][a-z]+)?"
)
PERSON = (
    r"(?:(?:[A-Z]\.\s?)+"
    + NAME_WORD
    + r"(?:\s+"
    + NAME_WORD
    + r"){0,2}|"
    + NAME_WORD
    + r"(?:\s+"
    + NAME_WORD
    + r"){1,3})"
)
BYLINE = re.compile(
    r"^(?:[Ee]dited\s+[Bb]y\s+|[Bb]y\s+)?" + PERSON + r"(?:\s*(?:&|and)\s*" + PERSON + r")?$"
)
BY_LINE = re.compile(r"^by\s+" + PERSON + r"(?:\s*(?:&|and)\s*" + PERSON + r")?$")
# Store and advert pages a conversion leaves in front of the story (D084).
FRONT_JUNK = re.compile(
    r"visit the (?:kobo|kindle|apple|google play|nook) store|to see the full black library range"
    r"|more warhammer[^.]{0,40} stories from black library|^\W*document outline\b",
    re.IGNORECASE,
)
OCR_SCAN = re.compile(
    r"produced in EPUB format by the Internet Archive|created with hocr-to-epub", re.IGNORECASE
)
FRONT_LABEL = re.compile(
    r"^(?:cover|title(?: page)?|half title|frontispiece|backlist|series|dedication"
    r"|warhammer(?: 40,?000| age of sigmar)?|imprint|map|maps)$",
    re.IGNORECASE,
)
SERIES_ITEM = re.compile(r"(?i)^book\s+(?:\d+|" + NUMBER_WORD + r")\s*[:.–—-]\s*\S")
BARE_DIVISION = re.compile(r"^(?:part|book)\s+\S+$", re.IGNORECASE)
FIRST_NUMBER = re.compile(r"^(?:chapter\s*[:.]?\s*)?(?:1|i|one)$", re.IGNORECASE)
BOOK_CHAPTER = re.compile(r"(?i)^((?:book|part)\s+\S+)\s*:\s*(chapter\s+(?:1|i|one))$")
FRONT_SCAN = 15  # spine pages looked at for store or advert pages before the story
FRONT_SHORT = 500  # words: a longer page is the story
STUB_TEXT = FRONT_SHORT  # words after a heading that make it a real chapter, never a stub
LONG_BOOK = 20000  # words; a longer book with under MIN_CHAPTERS headings is refused
MIN_CHAPTERS = 3
BOOK_ENTRIES = 5  # a novel inside an omnibus has at least this many contents entries
OPENING_WORDS = 50  # a heading without an id links to its file's start within this many words
GAP = 5  # at most this many chapter numbers are looked for in one gap
BIG_SECTION = 40000  # words under one entry with nothing under it: chapters the rebuild missed
TRAILING_WORDS = 100  # words after a last part or book title: fewer means a teaser, no part
# Inspection records short lines whose text is at most this long; longer lines are prose.
CAPTURE_CHARS = 100
CAPTURE_WORDS = 16

TITLE_SMALL = frozenset(
    "a an the of in on at to for from by with and or but into upon over under vs de von van du la le".split()  # noqa: SIM905 -- LF's word list, kept compact
)


DANGLING = frozenset("and or of the a an by with for to from in".split())  # noqa: SIM905


def prose(text):
    """A paragraph tagged as a heading that reads as a sentence, not a title."""
    words = text.split()
    end = text.rstrip()[-1:]
    if re.search(r"[.,!?][”’\"']$", text.rstrip()):
        return True
    if len(words) >= 2 and words[-1] in DANGLING:
        return True
    lower = [w for w in words if w[:1].islower()]
    if (
        len(words) >= 5
        and len(lower) * 5 >= len(words) * 2
        and sum(1 for w in lower if w.lower().strip(".,;:") not in TITLE_SMALL) >= 2
    ):
        return True
    return (
        len(words) > 12
        or len(text) > 100
        or (len(words) > 6 and end in ".!?")
        or (len(words) > 3 and end in ",;…")
        or text.rstrip().endswith("...")
        or (len(words) > 6 and (text.count(",") >= 2 or bool(re.search(r",\s+[a-z]", text))))
    )


UNITS = {
    word: index
    for index, word in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
        ]
    )
}
TENS = {
    word: 10 * index
    for index, word in enumerate(
        ["-", "-", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
    )
    if word != "-"
}
ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def number(text):
    """The integer a number spells: 12, XII (or xii), twelve, twenty-one; None otherwise."""
    value = text.strip()
    if value.isdigit():
        return int(value)
    if value and re.fullmatch(ROMAN, value.upper()) and value in (value.upper(), value.lower()):
        total = previous = 0
        for char in reversed(value.upper()):
            digit = ROMAN_VALUES[char]
            if digit < previous:
                total -= digit
            else:
                total += digit
                previous = digit
        return total or None
    words = [w for w in re.split(r"[- ]+", value.lower()) if w]
    if words and all(w in UNITS or w in TENS or w == "hundred" for w in words):
        total = 0
        for word in words:
            total = total * 100 if word == "hundred" else total + UNITS.get(word, TENS.get(word, 0))
        return total
    return None


def plain_label(label):
    """A heading's text as a contents label: soft hyphens out, a dotted I read as I."""
    return " ".join(label.replace("­", "").replace("İ", "I").replace("ı", "i").split()).rstrip(" ,;")


CHAPTER_LABEL = re.compile(
    r"^(?:chapter\s*[:.]?\s*)?(\d+|" + ROMAN + r"|(?i:" + NUMBER_WORD + r"))$", re.IGNORECASE
)


def chapter_number(label):
    """The number of a bare chapter heading ("CHAPTER TWENTY-FOUR", "24", "XXIV"), else None."""
    match = CHAPTER_LABEL.match(plain_label(label))
    return number(match.group(1)) if match else None


# A number, then optionally a title after a colon, full stop or spaced dash.
NUMBERED_LABEL = re.compile(
    r"^(?:(chapter|part|book)\s*[:.]?\s+)?(\d+|" + ROMAN + r"|(?i:" + NUMBER_WORD + r"))"
    r"(?:\s*:\s*\S.*|(?:(?<=\d)\.\s+|\s+[–—-]\s+|\s*[–—]\s*)[^\W\d_].*)?$",
    re.IGNORECASE,
)
# "CHAPTER THIRTEEN FORTIFICATION": after the division and its number, a title may follow.
SPACED_TITLE = re.compile(
    r"^(chapter|part|book)\s*[:.]?\s+(\d+|" + ROMAN + r"|(?i:" + NUMBER_WORD + r"))\s+[^\W\d_].*$",
    re.IGNORECASE,
)


def numbered(label, binary=False):
    """(kind, n) for a numbered entry, else None; four-digit or zero-padded numbers are times."""
    match = NUMBERED_LABEL.match(plain_label(label)) or SPACED_TITLE.match(plain_label(label))
    if not match:
        return None
    kind, digits = (match.group(1) or "chapter").lower(), match.group(2)
    if binary and set(digits) <= {"0", "1"}:
        return kind, int(digits, 2)
    if (
        re.fullmatch(ROMAN, digits.upper())
        and not digits.isdigit()
        and not re.fullmatch(r"(?i)" + NUMBER_WORD, digits)
        and digits != digits.upper()
    ):
        return None
    if digits.isdigit() and (len(digits) >= 4 or (len(digits) > 1 and digits[0] == "0")):
        return None
    value = number(digits)
    return None if value is None else (kind, value)


def number_key(label, binary=False):
    """((kind, style), n) for a numbered label; "Book One: Chapter One" is chapter one."""
    inner = re.match(r"(?i)(?:book|part)\s+\S+\s*:\s*(chapter\s+\S+)$", plain_label(label))
    if inner:
        return number_key(inner.group(1), binary)
    found = numbered(label, binary)
    if not found:
        return None
    match = NUMBERED_LABEL.match(plain_label(label)) or SPACED_TITLE.match(plain_label(label))
    assert match is not None  # numbered() matched the same label
    digits = match.group(2)
    style = (
        "digits"
        if digits.isdigit()
        else "words"
        if re.match(r"(?i)" + NUMBER_WORD + r"$", digits)
        else "roman"
    )
    return (found[0], style), found[1]


def numbering_problems(items):
    """Chapter, part and book numbers out of order, repeated or with a gap.

    items are (label, level[, page]) in reading order. Each kind and style runs on its own
    and may restart at 1; a gap between entries on the same or next page is the book's own.
    """
    digits = [
        m.group(2)
        for m in (NUMBERED_LABEL.match(" ".join(label.split())) for label, *_ in items)
        if m and m.group(2).isdigit()
    ]
    binary = len(digits) >= 5 and all(set(d) <= {"0", "1"} for d in digits)
    problems = []
    runs: dict = {}
    pages: dict = {}
    sizes = collections.Counter(
        key[0] for key in (number_key(label, binary) for label, *_ in items) if key
    )
    for item in items:
        label, _level, page = (tuple(item) + (None,))[:3]
        found = number_key(label, binary)
        if not found:
            continue
        key, value = found
        kind = key[0]
        previous = runs.get(key)
        runs[key] = value
        before, pages[key] = pages.get(key), page
        if value in (0, 1):
            continue
        if previous is None:
            if kind == "chapter" and sizes[key] >= 2:
                problems.append(f"{kind} {value} is the first ({label})")
        elif value == previous:
            problems.append(f"{kind} {value} repeated")
        elif value < previous:
            problems.append(f"{kind} {value} after {previous}")
        elif value > previous + 1 and not (
            page is not None and before is not None and 0 <= page - before <= 1
        ):
            problems.append(f"{kind} {previous + 1} missing before {label}")
    return problems


def heading_key(text):
    return " ".join(re.sub(r"[-‐-―]", " ", re.sub("[‘’ʼ`]", "'", text)).lower().split())


def undoubled(label):
    """A heading whose text is printed twice ("CHAPTER ONE CHAPTER ONE"), once."""
    words = label.split()
    half = len(words) // 2
    return (
        " ".join(words[:half])
        if half and len(words) % 2 == 0 and words[:half] == words[half:]
        else label
    )


def name_key(text):
    return " ".join(
        re.sub(
            r"[^\w\s]", " ", re.sub(r"(?i)^(?:edited\s+)?by\s+", "", text.strip()).lower()
        ).split()
    )


def creators(names):
    """The book's own author names as name keys of two or more words."""
    return {key for name in names if len((key := name_key(name)).split()) >= 2}


def running_header(label, names):
    """A page header kept as a heading: one of the book's authors, then a title."""
    key = name_key(label)
    return any(key.startswith(name + " ") for name in names)


def author_line(label, names):
    """The label names one of the book's own authors (or two joined by & / and)."""
    parts = [part for part in re.split(r"\s*(?:&|\band\b)\s*", label) if part.strip()]
    return name_key(label) in names or bool(parts) and all(name_key(p) in names for p in parts)


def chapterish(text):
    return bool(
        STYLED_HEADING.match(text)
        or CHAPTER_NUMBER.match(text)
        or BARE_DIVISION.match(text)
        or NUMBERED_TITLE.match(text)
    )


def title_line(text):
    """A short line that could title a chapter: at most ten words, no sentence ending."""
    return (
        len(text.split()) <= 10
        and len(text) <= 80
        and not prose(text)
        and not re.search(r"[.!?…\"”’']$", text.rstrip())
    )


def junk_entry(label):
    """A contents entry for a page around the story, never a chapter."""
    label = " ".join(label.split())
    return bool(
        NOT_A_CHAPTER.match(label)
        or re.match(r"(?i)cover$", label)
        or re.fullmatch(r"\[\d+\],?", label)
        or prose(label)
    )


def clean_list(labels):
    """Three or more entries, no file-name, placeholder or prose labels, mostly distinct."""
    count = len(labels)
    return (
        count >= MIN_CHAPTERS
        and not any(JUNK_LABEL.match(x) or HEADING_JUNK.match(x) or prose(x) for x in labels)
        and len({x.lower() for x in labels}) * 10 >= count * 6
    )


def numbered_label(label):
    return bool(CHAPTER_NUMBER.match(label) or re.match(r"(?i)chapter\s*[:.]?\s*\S+$", label))


def capturable(text):
    """Inspection records a short line when the planner's rules could read it as a title."""
    return (
        bool(text)
        and len(text) <= CAPTURE_CHARS
        and len(text.split()) <= CAPTURE_WORDS
        and bool(
            title_line(text)
            or chapterish(text)
            or NUMBERED_LABEL.match(text)
            or SPACED_TITLE.match(text)
            or BYLINE.match(text)
            or BY_LINE.match(text)
        )
    )
