"""Closed DOCTYPE vocabulary; HTML character references need no DTD resolver."""

import re
from html.entities import name2codepoint
from xml.parsers import expat

XHTML_DTDS = {
    "-//W3C//DTD XHTML 1.0 Strict//EN": "http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd",
    "-//W3C//DTD XHTML 1.0 Transitional//EN": "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd",
    "-//W3C//DTD XHTML 1.0 Frameset//EN": "http://www.w3.org/TR/xhtml1/DTD/xhtml1-frameset.dtd",
    "-//W3C//DTD XHTML 1.1//EN": "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd",
}
# Ignore literal examples in comments, CDATA and processing instructions.
LEXEMES = re.compile(
    rb"<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<\?[\s\S]*?\?>|&([A-Za-z][A-Za-z0-9]*);"
)


class UnsafeDTD(ValueError):
    pass


def doctype(name, pubid, system, internal=False):
    if (
        internal
        or name != "html"
        or not (
            pubid is None and system is None or pubid in XHTML_DTDS and system == XHTML_DTDS[pubid]
        )
    ):
        raise UnsafeDTD


def character_edits(data):
    """LF's HTML4 name table, as numeric references; never user-defined entities."""
    edits = []
    for match in LEXEMES.finditer(data):
        if match[1] is None:
            continue
        name = match[1].decode("ascii")
        if name not in {"amp", "lt", "gt", "quot", "apos"} and name in name2codepoint:
            edits.append((match.start(), match.end(), f"&#{name2codepoint[name]};".encode()))
    return edits


def prepared(data):
    edits = character_edits(data)
    parts: list[bytes] = []
    cursor = 0
    for start, end, value in edits:
        parts.extend((data[cursor:start], value))
        cursor = end
    return b"".join(parts + [data[cursor:]]), edits


def guard(data):
    """Expat rejects subsets before declarations or references can be expanded."""
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.StartDoctypeDeclHandler = lambda name, system, pubid, internal: doctype(
        name, pubid, system, internal
    )

    def forbidden(*args):
        raise UnsafeDTD

    parser.EntityDeclHandler = forbidden
    parser.ExternalEntityRefHandler = forbidden
    parser.Parse(data, True)


def html_doctype_edit(data):
    tokens = re.compile(
        rb"<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<\?[\s\S]*?\?>|(?P<doctype><!DOCTYPE\s+html\s+PUBLIC\s+[^>]+>)"
    )
    for match in tokens.finditer(data):
        if match["doctype"] is not None:
            return match.start(), match.end(), b"<!DOCTYPE html>"
    return None
