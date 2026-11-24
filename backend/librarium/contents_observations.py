"""Bounded contents observations for one parsed XHTML body, inside the isolated inspection.

Library Finish's contents rules read short paragraph lines as well as headings: styled
chapter markers, bare numbers, story titles and their bylines (LF 72bdf39
bin/epub_content.py:40-87 TextEvidence, 813-892). Inspection v10 records only the lines
those rules could read as a title (``contents_rules.capturable``), a page's opening line
styled as a title, the short line above a byline-shaped heading and the short line under
a bare Part, Book or Roman-numeral heading, plus per-page counts and flags. Other prose is
never recorded. Positions match the heading observations.
"""

import re
from bisect import bisect_left
from xml.etree.ElementTree import Element

from librarium import contents_rules as rules

BLOCK_NAMES = ("p", "div")
INLINE_NAMES = ("b", "strong")
STRUCTURE_NAMES = BLOCK_NAMES + tuple(f"h{level}" for level in range(1, 7))
LEAD_CHARS = 4000  # LF reads a page's first 4000 characters for publisher marks
FRONT_LEAD_CHARS = 300
FIRST_TEXT_CHARS = 3000
ABOVE_HEADING_WORDS = 8
DIVISION_TITLE_WORDS = 6  # LF joins "PART ONE" with a following title of at most six words
STYLED_CHARS = 60
STYLED_CLASS = re.compile(r"chapter|title|heading", re.IGNORECASE)
INLINE_CHARS = 40


XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def has_id(element):
    """An id attribute is present, even empty; a new anchor would duplicate it."""
    return "id" in element.attrib or XML_ID in element.attrib


class _Text:
    """Normalized subtree text with the non-space characters inside ``a[href]`` links."""

    def __init__(self, element, xhtml, boundaries, skipped):
        self.parts: list[str] = []
        self.chars = self.linked = 0
        self.xhtml, self.boundaries, self.skipped = xhtml, boundaries, skipped
        self._walk(element, False)
        self.text = " ".join("".join(self.parts).split())

    def _add(self, text, linked):
        if text:
            self.parts.append(text)
            count = len("".join(text.split()))
            self.chars += count
            self.linked += count if linked else 0

    def _walk(self, node, linked):
        if node.tag in self.skipped:
            return
        linked = linked or (node.tag == self.xhtml + "a" and bool(node.get("href")))
        if node.tag in self.boundaries:
            self.parts.append(" ")
        self._add(node.text, linked)
        for child in node:
            self._walk(child, linked)
            if child.tag in self.boundaries:
                self.parts.append(" ")
            self._add(child.tail, linked)

    @property
    def only_link(self):
        return bool(self.chars) and self.linked >= self.chars


def _leaf(element, xhtml):
    return not any(
        node is not element and node.tag in {xhtml + name for name in STRUCTURE_NAMES}
        for node in element.iter()
    )


def _ends_paragraph(paragraph, inline):
    """``inline`` is the last thing in ``paragraph``: only closing wrappers follow it."""
    node = paragraph
    while len(node):
        last = node[-1]
        if (last.tail or "").strip():
            return False
        if last is inline:
            return not len(inline) and bool((inline.text or "").strip())
        node = last
    return False


def observe(body, positions, headings, heading_elements, xhtml, boundaries, skipped):
    """(signals, blocks, heading flags) for one body; ``positions`` maps elements to offsets.

    Records stay compact: a flag or count appears only when it is set, so ordinary pages
    and headings add a few bytes at most.
    """
    names = {xhtml + name for name in BLOCK_NAMES}
    inline_names = {xhtml + name for name in INLINE_NAMES}
    page = _Text(body, xhtml, boundaries, skipped).text
    lead = page[:LEAD_CHARS]
    counts = {"blocks": 0, "link_blocks": 0, "byline_blocks": 0}
    rows: list[tuple[Element, str, int | None, bool]] = []
    ordinal = 0
    first_line_link = False
    for element in body.iter():
        if element not in positions:
            continue
        if element.tag in names and _leaf(element, xhtml):
            line = _Text(element, xhtml, boundaries, skipped)
            if not line.text:
                continue
            counts["blocks"] += 1
            if counts["blocks"] == 1 and line.only_link:
                first_line_link = True  # LF's title-style vote skips a page that opens with a link
            counts["link_blocks"] += line.only_link
            counts["byline_blocks"] += bool(rules.BYLINE.match(line.text))
            if line.only_link:
                continue
            rows.append((element, line.text, ordinal, False))
            ordinal += 1
            for inline in element.iter():
                if (
                    inline.tag in inline_names
                    and inline in positions
                    and _ends_paragraph(element, inline)
                ):
                    label = " ".join((inline.text or "").split())
                    if len(label) <= INLINE_CHARS and rules.number_key(label):
                        rows.append((inline, label, None, True))
    beside = set()
    paragraphs = [row for row in rows if not row[3]]
    starts = [positions[row[0]]["source_index"] for row in paragraphs]
    for heading in headings:
        if heading["word_offset"] is None:
            continue
        label = rules.plain_label(heading["label"])
        if rules.BARE_DIVISION.match(label) or re.fullmatch(rules.ROMAN, label):
            # The line under "PART ONE" may be its title, even when it ends in "…" (LF join).
            index = bisect_left(starts, heading["source_index"])
            if index < len(paragraphs):
                element, text, _, _ = paragraphs[index]
                if len(text.split()) <= DIVISION_TITLE_WORDS:
                    beside.add(element)
        if not rules.BYLINE.match(heading["label"]):
            continue
        # LF reads the line above a heading only to tell a story title from its byline.
        index = bisect_left(starts, heading["source_index"]) - 1
        if index < 0:
            continue
        element, text, _, _ = paragraphs[index]
        gap = heading["word_offset"] - positions[element]["word_offset"] - len(text.split())
        if 0 <= gap <= 2 and len(text.split()) <= ABOVE_HEADING_WORDS:
            beside.add(element)
    blocks = []
    for element, text, position_in_page, inline in rows:
        label = rules.plain_label(text)
        styled_opening = (
            position_in_page == 0
            and len(label) <= STYLED_CHARS
            and bool(STYLED_CLASS.search(element.get("class", "")))
            and not rules.prose(label)
        )
        if (
            not (inline or styled_opening or element in beside or rules.capturable(label))
            or len(text) > rules.CAPTURE_CHARS
        ):
            continue
        block = {"label": text, "ordinal": position_in_page, **positions[element]}
        block.update(_identity(element))
        name = " ".join(element.get("class", "").split())[: rules.CAPTURE_CHARS]
        if name:
            block["class"] = name
        if inline:
            block["inline"] = True
        blocks.append(block)
    flags = []
    for element in heading_elements:
        flag = {key: value for key, value in _identity(element).items() if key == "has_id"}
        if _Text(element, xhtml, boundaries, skipped).only_link:
            flag["only_link"] = True
        flags.append(flag)
    blocks_seen = counts["blocks"]
    signals = {
        # LF's backlist pages: store-link titles, or titles over author lines.
        "backlist_links": blocks_seen >= 4 and counts["link_blocks"] * 5 >= blocks_seen * 2,
        "backlist_bylines": blocks_seen >= 4 and counts["byline_blocks"] * 3 >= blocks_seen,
        "publisher_marks": len({m.lower() for m in rules.PUBLISHER_PAGE.findall(lead)}),
        "front_junk_lead": bool(rules.FRONT_JUNK.search(page[:FRONT_LEAD_CHARS])),
        "front_junk": bool(rules.FRONT_JUNK.search(page[:FIRST_TEXT_CHARS])),
        "ocr_scan": bool(rules.OCR_SCAN.search(page[:FIRST_TEXT_CHARS])),
        "first_line_link": first_line_link,
    }
    return {key: value for key, value in signals.items() if value}, blocks, flags


def _identity(element):
    """The element's own id, or ``has_id`` when an empty id attribute blocks a new anchor."""
    ident = element.get("id") or element.get(XML_ID)
    if ident:
        return {"id": ident}
    return {"has_id": True} if has_id(element) else {}


POLICY = "librarium.contents-observations.v1"


def observed(blocks):
    return {"policy": POLICY, "status": "recorded", "blocks": blocks, "reason": None}


def unobserved(reason):
    return {"policy": POLICY, "status": "unconfirmed", "reason": reason}
