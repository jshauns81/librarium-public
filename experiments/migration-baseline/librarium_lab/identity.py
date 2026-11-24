"""Read-only helper slice; upstream provenance is recorded in docs/architecture.md."""

import re
import unicodedata


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    value = re.sub(r"\(.*?\)|\[.*?\]", "", value)
    value = re.sub(r"^(the|a|an)\s+", "", value.strip())
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def work_key(title: str, authors: str) -> str:
    title_key = norm(re.split(r":\s", title or "")[0]) or norm(title)
    first = (authors or "").split("&")[0].strip()
    last = norm(first.split(",")[0] if "," in first else (first.split() or [""])[-1])
    if last in ("unknown", "various", ""):
        last = ""
    return f"{title_key}|{last}"


def check13(first12: str) -> str:
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(first12))
    return str((10 - total % 10) % 10)


def to_isbn13(raw: str) -> str | None:
    raw = re.sub(r"^\s*ISBN(?:[-\s]?(?:10|13)(?=\D))?\s*:?", "", raw, flags=re.IGNORECASE)
    code = re.sub(r"[^\dXx]", "", raw).upper()
    if len(code) == 10 and re.fullmatch(r"\d{9}[\dX]", code):
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(code))
        if total % 11 == 0:
            body = "978" + code[:9]
            return body + check13(body)
    if len(code) == 13 and code.isdecimal() and check13(code[:12]) == code[12]:
        return code
    return None
