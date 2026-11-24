"""XML 1.0 NCName lexical checks for captured IDs and EPUB prefix mappings."""

import re

XML_WHITESPACE = " \t\r\n"
_START = (
    r"A-Z_a-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u02FF\u0370-\u037D"
    r"\u037F-\u1FFF\u200C-\u200D\u2070-\u218F\u2C00-\u2FEF\u3001-\uD7FF"
    r"\uF900-\uFDCF\uFDF0-\uFFFD\U00010000-\U000EFFFF"
)
_NAME = re.compile(f"[{_START}][{_START}0-9.\\-\u00b7\u0300-\u036f\u203f-\u2040]*\\Z")


def valid_ncname(value):
    return isinstance(value, str) and _NAME.fullmatch(value) is not None
