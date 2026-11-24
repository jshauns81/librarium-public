import unicodedata


def bounded_text(value: str, limit: int) -> bool:
    return len(value) <= limit and not any(
        unicodedata.category(char) in {"Cc", "Cs"} for char in value
    )
