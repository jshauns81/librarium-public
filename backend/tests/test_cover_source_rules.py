"""Retained provider rules, exercised without network calls."""

import pytest
from librarium import cover_source_rules as rules


@pytest.mark.parametrize("suffix", ["100x100bb.jpg", "100x100bb.png", "100x100bb.webp"])
def test_apple_requests_bounded_artwork(suffix):
    assert rules.apple_hires("https://is1-ssl.mzstatic.com/art/" + suffix) == [
        "https://is1-ssl.mzstatic.com/art/1600x1600bb.jpg"
    ]


def test_omnibus_guard_and_isbn_title_containment():
    assert rules.kind_mismatch("Trollslayer", "Gotrek & Felix Omnibus")
    assert not rules.isbn_match(
        "Trollslayer",
        "William King",
        {"title": "Gotrek & Felix: Trollslayer stories", "author": "William King"},
    )
    assert rules.isbn_match(
        "Hero of the Imperium",
        "Sandy Mitchell",
        {"title": "Ciaphas Cain: Hero of the Imperium (Omnibus)", "author": "Mitchell, Sandy"},
    )


def test_ranking_prefers_similar_art_and_gives_every_choice_a_reason():
    fp = {"g": [1.0], "c": [0.5]}
    cands = [
        {
            "id": str(i),
            "title": "Novel",
            "author": "Author",
            "width": 600,
            "height": 900 + i,
            "by_isbn": False,
            "_fp": fp,
        }
        for i in range(3)
    ]
    rules.score(cands, "Novel", "Author")
    result = rules.rank(cands, fp, "Novel")
    assert result[0]["recommended"] and result[0]["look"] == 1
    assert all(c["why"] for c in result)


@pytest.mark.parametrize(
    "isbn,expected", [("0-306-40615-2", "9780306406157"), ("9780306406158", None)]
)
def test_isbn_checksum(isbn, expected):
    assert rules.isbn13(isbn) == expected
