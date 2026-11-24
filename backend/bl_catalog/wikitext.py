"""
Shared wikitext parsing: {{Infobox book}} extraction and markup cleaning.

Used by the Fandom adapter and the Lexicanum inbox importer. The infobox regex
accepts Fandom's ``{{Infobox book}}`` and Lexicanum's ``{{Book}}``.
"""

from __future__ import annotations

import re

# Matches only the book infoboxes: Fandom's {{Infobox book}} / {{Infobox novel}} and Lexicanum's
# {{Book}} and {{Short}} (short stories). The name must be followed by "|", "}}" or a comment, so
# templates that merely start with the same letters ({{Infobox character}}, {{Book-nav}},
# {{Shortcut}}) are not taken for a book.
_INFOBOX_START_RE = re.compile(
    r"\{\{\s*(?:Infobox[ _](?:book|novel)|Book|Short)(?=\s*(?:[|}]|<!--))", re.IGNORECASE
)

# [[File:...]] / [[Image:...]] embeds (may contain pipes — strip before splitting)
_FILE_LINK_RE = re.compile(r"\[\[(?:File|Image):[^\]]*\]\]", re.IGNORECASE)
# [[target|display]] → display, [[target]] → target
_WIKI_LINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]|]+)\]\]")
# {{template|...}} leftovers inside values
_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
_REF_RE = re.compile(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", re.DOTALL)


def find_infobox(wikitext: str) -> str | None:
    """Return the raw text of the first infobox template, or None."""
    m = _INFOBOX_START_RE.search(wikitext)
    if not m:
        return None
    depth = 0
    start = m.start()
    i = start
    while i < len(wikitext) - 1:
        pair = wikitext[i : i + 2]
        if pair == "{{":
            depth += 1
            i += 2
        elif pair == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return wikitext[start:i]
        else:
            i += 1
    return None


def parse_infobox(wikitext: str) -> dict[str, str]:
    """
    Parse the first infobox in `wikitext` into a dict of
    lowercase-key → cleaned-value. Returns {} if no infobox found.
    """
    box = find_infobox(wikitext)
    if not box:
        return {}

    fields: dict[str, str] = {}
    # Field lines start with '|' at top template depth; the infobox body is
    # line-oriented in practice. Strip file links first so their pipes don't
    # confuse the key=value split.
    body = _FILE_LINK_RE.sub("", box)
    for line in body.splitlines():
        line = line.strip().lstrip("|").strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        value = clean_wiki_value(value)
        if key and value:
            fields[key] = value
    return fields


def clean_wiki_value(raw: str) -> str:
    """Strip wiki markup from an infobox value or table cell."""
    s = _REF_RE.sub("", raw)
    s = _FILE_LINK_RE.sub("", s)
    s = _WIKI_LINK_RE.sub(r"\1", s)
    s = _TEMPLATE_RE.sub("", s)
    s = s.replace("'''", "").replace("''", "")
    s = re.sub(r"<[^>]+>", "", s)  # remaining html tags
    s = re.sub(r"\s+", " ", s)
    # Trailing template/table junk
    return s.strip().strip("}").strip()
