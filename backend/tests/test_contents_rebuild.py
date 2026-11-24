"""Library Finish's contents-rebuild cases, re-run through Librarium's inspection and planner.

Synthetic EPUBs follow LF 72bdf39 tests/contents_rebuild_test.py, whose fixtures model the
2026-10-24 survey shapes (parts, styled chapters, omnibus novels). No book bytes are used.
"""

import hashlib
import io
import zipfile

import pytest
from librarium.epub_inspection import inspect_bytes

X = "http://www.w3.org/1999/xhtml"
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
WORDS = ["ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN"]


def page(body):
    return f'<html xmlns="{X}"><head><title>t</title></head><body>{body}</body></html>'.encode()


def prose(n, word="story"):
    return "<p>" + " ".join([word] * n) + ".</p>"


def ncx(labels):
    points = "".join(
        f'<navPoint id="o{k}" playOrder="{k}"><navLabel><text>{label}</text></navLabel>'
        f'<content src="{src}"/></navPoint>'
        for k, (label, src) in enumerate(labels, 1)
    )
    return (
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head>'
        '<meta name="dtb:uid" content="urn:test:kc"/></head><docTitle><text>T</text></docTitle>'
        f"<navMap>{points}</navMap></ncx>"
    ).encode()


def make(docs, old, *, version="2.0", nav=None, title="T", creator=None, media=()):
    """An EPUB whose ordered ``docs`` are {path: bytes}; ``old`` is the NCX [(label, src)]."""
    items = "".join(
        f'<item id="d{i}" href="{path}" media-type="application/xhtml+xml"/>'
        for i, path in enumerate(docs)
    )
    if nav is not None:
        items += (
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        )
    spine = "".join(f'<itemref idref="d{i}"/>' for i, _ in enumerate(docs))
    author = f"<dc:creator>{creator}</dc:creator>" if creator else ""
    opf = (
        f'<package xmlns="http://www.idpf.org/2007/opf" version="{version}" '
        'unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:identifier id="uid">urn:test:kc</dc:identifier><dc:title>{title}</dc:title>'
        f"{author}<dc:language>en</dc:language></metadata><manifest>{items}"
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>'
        f'<spine toc="ncx">{spine}</spine></package>'
    ).encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), b"application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
            '<rootfiles><rootfile full-path="book.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        z.writestr("book.opf", opf)
        z.writestr("toc.ncx", ncx(old))
        if nav is not None:
            links = "".join(f'<li><a href="{src}">{label}</a></li>' for label, src in nav)
            z.writestr(
                "nav.xhtml",
                f'<html xmlns="{X}" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>t'
                f'</title></head><body><nav epub:type="toc"><ol>{links}</ol></nav></body></html>',
            )
        for path, body in docs.items():
            z.writestr(path, body)
        for path in media:
            z.writestr(path, b"synthetic image bytes")
    return stream.getvalue()


def plan(data):
    report = inspect_bytes(data, hashlib.sha256(data).hexdigest())
    assert report["inspection_complete"] is True, report["findings"]
    return report["contents_plan"]


def tree(entries):
    return [(e["label"], [c["label"] for c in e["children"]]) for e in entries]


def labels(entries):
    return [e["label"] for e in entries]


def chapters(n=10):
    return {
        f"c{k:02d}.html": page(f'<h2 id="c{k}">Chapter {k + 1}</h2>{prose(300)}') for k in range(n)
    }


def clean_old(targets):
    return [(f"Chapter {k + 1}", target) for k, target in enumerate(targets)]


def brothers(chapter_ids=False):
    """Parts in short files (h1 PART + bold subtitle), h3 chapters in the next file."""
    docs = {"front.html": page(prose(200, "blurb"))}
    old = []
    parts = ["ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN"]
    subtitles = ["GREY DAWN", "THE DEAD PLACE", "THE SCHOLA", "THE MOMENT", "THE MASTER"]
    subtitles += ["DARK EAGLES", "ENDGAME"]
    for n, (part, sub) in enumerate(zip(parts, subtitles, strict=True)):
        docs[f"p{n}.html"] = page(
            f'<h1 id="t{n}"><b>PART {part}</b></h1><p><b>{sub}</b></p><p><b>Undertaking</b></p>'
        )
        body = "".join(
            f"<h3{f' id="c{n}_{k}"' if (k == 0 or chapter_ids) else ''}><b>{r}</b></h3>{prose(400)}"
            for k, r in enumerate(ROMAN[:4])
        )
        if n == 4:
            body = (
                '<h2 id="junk">Chapter Master Seydon was just a shadow: robed, mysterious and '
                "towering. His cloak was made of broken wyrm-horn.</h2>" + body
            )
        docs[f"c{n}.html"] = page(body)
        old.append((f"PART {part}", f"p{n}.html"))
    junk = (
        "Chapter Master Seydon was just a shadow: robed, mysterious and towering. His cloak "
        "was made of broken wyrm-horn."
    )
    old.insert(5, (junk, "c4.html#junk"))
    return make(docs, old)


def test_parts_list_their_titles_and_chapters_and_missing_anchors_are_required():
    result = plan(brothers())
    assert result["policy_version"] == "librarium.contents-plan.v2"
    assert result["decision"] == "propose"
    assert result["reason_codes"] == ["chapter_headings"]
    assert labels(result["entries"]) == [
        "PART ONE: GREY DAWN",
        "PART TWO: THE DEAD PLACE",
        "PART THREE: THE SCHOLA",
        "PART FOUR: THE MOMENT",
        "PART FIVE: THE MASTER",
        "PART SIX: DARK EAGLES",
        "PART SEVEN: ENDGAME",
    ]
    assert all(children == ROMAN[:4] for _, children in tree(result["entries"]))
    first = result["entries"][0]
    assert first["origin"] == "joined_label"
    assert first["children"][0]["fragment"] == "c0_0"
    assert [c["requires_anchor"] for c in first["children"]] == [False, True, True, True]
    assert result["measures"]["headings"] == 35


def test_parts_hold_their_chapters_when_every_chapter_is_anchored():
    result = plan(brothers(chapter_ids=True))
    assert len(result["entries"]) == 7
    assert [(c["label"], c["fragment"]) for c in result["entries"][0]["children"]] == [
        ("I", "c0_0"),
        ("II", "c0_1"),
        ("III", "c0_2"),
        ("IV", "c0_3"),
    ]


def fleshworks(ids=False):
    """Two long converted files with bold 'CHAPTER: ONE' paragraphs and no headings."""

    def chapter(k, name):
        ident = f' id="f{k}"' if ids else ""
        return f'<p class="calibre_2"{ident}><span class="bold">CHAPTER: {name}</span></p>' + prose(
            1700
        )

    ident = ' id="f99"' if ids else ""
    first = f'<p class="calibre_2"{ident}><span class="bold">PROLOGUE</span></p>' + prose(1500)
    first += "".join(chapter(k, WORDS[k]) for k in range(7))
    later = ["EIGHT", "NINE", "TEN", "ELEVEN", "TWELVE", "THIRTEEN"]
    second = prose(900) + "".join(chapter(k, w) for k, w in enumerate(later, 7))
    return make(
        {
            "index_split_000.html": page(first),
            "index_split_001.html": page(second),
            "index_split_003.html": page(
                '<p>Table of Contents</p><p><a href="index_split_000.html">www.blacklibrary.com</a></p>'
            ),
        },
        [("www.blacklibrary.com", "index_split_000.html")],
    )


EXPECTED_FLESHWORKS = ["PROLOGUE"] + [
    "CHAPTER: " + w for w in WORDS[:7] + ["EIGHT", "NINE", "TEN", "ELEVEN", "TWELVE", "THIRTEEN"]
]


@pytest.mark.parametrize("ids", [True, False])
def test_styled_chapter_paragraphs_become_entries(ids):
    result = plan(fleshworks(ids=ids))
    assert result["decision"] == "propose"
    assert labels(result["entries"]) == EXPECTED_FLESHWORKS
    entries = result["entries"]
    assert all(e["origin"] == "paragraph" for e in entries)
    if ids:
        assert not any(e["requires_anchor"] for e in entries)
    else:
        # The prologue opens its file; the thirteen chapters need anchors on their paragraphs.
        assert entries[0]["fragment"] is None and not entries[0]["requires_anchor"]
        assert sum(e["requires_anchor"] for e in entries) == 13


def test_long_book_with_under_three_headings_is_held():
    data = make(
        {
            "a.html": page('<h1 id="a">ONE</h1>' + prose(11000)),
            "b.html": page('<h1 id="b">TWO</h1>' + prose(11000)),
        },
        [("Start", "a.html")],
    )
    result = plan(data)
    assert result["decision"] == "held"
    assert result["reason_codes"] == ["too_few_headings"]
    assert result["measures"]["headings"] == 2


def test_short_book_with_two_headings_is_rebuilt():
    data = make(
        {
            "a.html": page('<h1 id="a">ONE</h1>' + prose(500)),
            "b.html": page('<h1 id="b">TWO</h1>' + prose(500)),
        },
        [("Start", "a.html")],
    )
    assert labels(plan(data)["entries"]) == ["ONE", "TWO"]


def test_a_placeholder_start_label_is_replaced_by_one_entry_per_chapter():
    docs = {"index_split_001.html": page(prose(800, "intro"))}
    docs.update(
        {
            f"index_split_{k + 2:03d}.html": page(f'<h2 id="calibre_toc_{k}">{w}</h2>{prose(2000)}')
            for k, w in enumerate(WORDS)
        }
    )
    result = plan(make(docs, [("Start", "index_split_001.html")]))
    assert result["decision"] == "propose"
    assert labels(result["entries"]) == WORDS


def test_omnibus_novel_titles_hold_their_chapters():
    docs = {}
    for n, title in enumerate(["First and Only", "Ghostmaker", "Necropolis"]):
        docs[f"n{n}.html"] = page(f'<h1 id="n{n}">{title}</h1><p>A synthetic novel.</p>')
        for k, w in enumerate(["One", "Two", "Three"]):
            docs[f"n{n}_{k}.html"] = page(f'<h2 id="h{n}_{k}">{w}</h2>{prose(300)}')
    result = plan(make(docs, [("Start", "n0.html")]))
    assert tree(result["entries"]) == [
        (title, ["One", "Two", "Three"]) for title in ["First and Only", "Ghostmaker", "Necropolis"]
    ]


def test_omnibus_with_picture_titles_groups_restarting_chapters_by_book():
    docs = {}
    old = []
    for n in range(3):
        docs[f"t{n}.html"] = page(f'<p><img src="t{n}.jpg" alt=""/></p>')
        docs[f"p{n}.html"] = page(f'<h2 id="p{n}">PROLOGUE</h2>{prose(300)}')
        for k, r in enumerate(ROMAN[:5]):
            docs[f"c{n}_{k}.html"] = page(f'<h3 id="c{n}_{k}">{r}</h3>{prose(300)}')
        docs[f"e{n}.html"] = page(f'<h2 id="e{n}">EPILOGUE</h2>{prose(200)}')
        old += [("PROLOGUE", f"p{n}.html#p{n}"), ("EPILOGUE", f"e{n}.html#e{n}")]
    data = make(docs, old, media=[f"t{n}.jpg" for n in range(3)])
    result = plan(data)
    assert labels(result["entries"]) == ["Book 1", "Book 2", "Book 3"]
    book = result["entries"][1]
    assert [c["label"] for c in book["children"]] == ["PROLOGUE", *ROMAN[:5], "EPILOGUE"]
    assert book["origin"] == "numbered_book"
    assert (book["path"], book["fragment"]) == ("p1.html", "p1")


def test_text_titles_at_chapter_level_hold_their_novels():
    docs = {}
    for n, title in enumerate(["Iron Company", "Grimblades"]):
        docs[f"t{n}.html"] = page(f'<h2 id="t{n}">{title}</h2><p>A novel.</p>')
        for k, w in enumerate(WORDS[:6]):
            docs[f"c{n}_{k}.html"] = page(f'<h2 id="c{n}_{k}">{w}</h2>{prose(300)}')
    result = plan(make(docs, [("Start", "t0.html")]))
    assert [
        (e["label"], e["fragment"], [c["label"] for c in e["children"]]) for e in result["entries"]
    ] == [
        ("Iron Company", "t0", WORDS[:6]),
        ("Grimblades", "t1", WORDS[:6]),
    ]


def test_a_section_heading_stays_under_its_chapter_in_the_same_file():
    docs = {
        f"c{k}.html": page(
            f'<h2 id="c{k}">Chapter {k + 1}</h2>{prose(200)}<h3 id="s{k}">Interlude {k + 1}</h3>'
            + prose(200)
        )
        for k in range(3)
    }
    result = plan(make(docs, [("Start", "c0.html")]))
    assert tree(result["entries"]) == [
        (f"Chapter {k + 1}", [f"Interlude {k + 1}"]) for k in range(3)
    ]


def test_a_clean_short_list_is_kept_against_a_shorter_rebuild():
    docs = {
        "p.html": page('<h1 id="p">Prologue</h1>' + prose(300)),
        "m.html": page(prose(300)),
        "e.html": page('<h1 id="e">Epilogue</h1>' + prose(300)),
    }
    data = make(docs, [("Prologue", "p.html"), ("The Middle", "m.html"), ("Epilogue", "e.html")])
    result = plan(data)
    assert result["decision"] == "keep"
    assert result["reason_codes"] == ["rebuild_too_short"]


def test_chapters_below_a_sparse_middle_level_are_kept():
    docs = {"pro.html": page('<h2 id="pro">Prologue</h2>' + prose(300))}
    for n in range(2):
        docs[f"p{n}.html"] = page(f'<h1 id="p{n}">Part {["One", "Two"][n]}</h1>')
        for k in range(3):
            docs[f"c{n}_{k}.html"] = page(
                f'<h3 id="c{n}_{k}">Chapter {3 * n + k + 1}</h3>{prose(300)}'
            )
    docs["epi.html"] = page('<h2 id="epi">Epilogue</h2>' + prose(200))
    docs["ab.html"] = page('<h2 id="ab">About the Author</h2>' + prose(80))
    result = plan(make(docs, [("Start", "pro.html")]))
    assert tree(result["entries"]) == [
        ("Prologue", []),
        ("Part One", ["Chapter 1", "Chapter 2", "Chapter 3"]),
        ("Part Two", ["Chapter 4", "Chapter 5", "Chapter 6", "Epilogue"]),
        ("About the Author", []),
    ]


def test_a_series_list_page_of_headings_is_not_contents():
    docs = {
        "series.html": page(
            "".join(f'<h1 id="s{k}">Book {k + 1} – TITLE {k}</h1>' for k in range(12))
        )
    }
    docs.update(chapters(4))
    result = plan(make(docs, [("Start", "c00.html")]))
    assert labels(result["entries"]) == [f"Chapter {k + 1}" for k in range(4)]


def test_file_name_labels_are_not_a_clean_list():
    old = [(f"c{k:02d}.html", f"c{k:02d}.html#c{k}") for k in range(10)]
    result = plan(make(chapters(), old))
    assert result["decision"] == "propose"
    assert result["entries"][0]["label"] == "Chapter 1"


def test_placeholder_nav_labels_are_not_masked_by_a_clean_ncx():
    old = clean_old([f"c{k:02d}.html#c{k}" for k in range(4)])
    nav = [(f"index_split_{k:03d}", f"c{k:02d}.html#c{k}") for k in range(4)]
    result = plan(make(chapters(4), old, version="3.0", nav=nav))
    assert result["decision"] == "propose"


def test_clean_ncx_in_epub3_without_a_nav_document_is_rebuilt():
    old = clean_old([f"c{k:02d}.html#c{k}" for k in range(10)])
    result = plan(make(chapters(), old, version="3.0"))
    assert result["decision"] == "propose"


def test_styled_chapters_after_a_contents_heading_in_the_same_file_are_found():
    body = "<h1>Contents</h1>" + "".join(
        f'<p class="chapter" id="k{k}">Chapter {k + 1}</p>{prose(300)}' for k in range(4)
    )
    result = plan(make({"all.html": page(body)}, [("Start", "all.html")]))
    assert labels(result["entries"]) == [f"Chapter {k + 1}" for k in range(4)]


def test_unanchored_scene_numbers_do_not_outvote_the_chapters():
    docs = {}
    for n in range(2):
        docs[f"p{n}.html"] = page(f'<h1 id="p{n}">PART {WORDS[n]}</h1>')
        for k in range(3):
            docs[f"c{n}_{k}.html"] = page(
                f'<h2 id="c{n}_{k}">{WORDS[3 * n + k]}</h2>'
                + "".join(f"<h3>{r}</h3>{prose(150)}" for r in ROMAN[:4])
            )
    result = plan(make(docs, [("Start", "p0.html")]))
    assert tree(result["entries"]) == [("PART ONE", WORDS[:3]), ("PART TWO", WORDS[3:6])]


def test_a_numbered_title_opening_a_file_is_a_heading():
    titles = ["THE SPIRE", "FRESH AIR", "THE HEIGHTS"]
    docs = {
        f"c{k}.html": page(f'<p class="calibre13" id="page_{k}">{k + 1}: {t}</p>{prose(300)}')
        for k, t in enumerate(titles)
    }
    docs["n.html"] = page(prose(300) + "<p>4: not a heading mid-file</p>" + prose(50))
    result = plan(make(docs, [("Start", "c0.html")]))
    assert labels(result["entries"]) == ["1: THE SPIRE", "2: FRESH AIR", "3: THE HEIGHTS"]


def test_refusals_name_their_reason():
    for count, reason in ((0, "no_chapter_headings"), (1, "too_few_headings")):
        heads = [f'<h1 id="h{k}">ONE</h1>' for k in range(count)] + [""] * (2 - count)
        data = make(
            {"a.html": page(heads[0] + prose(10999)), "b.html": page(heads[1] + prose(10999))},
            [("Start", "a.html")],
        )
        result = plan(data)
        assert result["decision"] == "held"
        assert result["reason_codes"] == [reason]


def test_prologue_never_holds_the_chapters():
    docs = {"p.html": page('<h2 id="p">PROLOGUE</h2>' + prose(300))}
    docs.update(
        {f"c{k}.html": page(f'<h3 id="c{k}">{r}</h3>{prose(300)}') for k, r in enumerate(ROMAN[:6])}
    )
    docs["e.html"] = page('<h2 id="e">EPILOGUE</h2>' + prose(200))
    result = plan(make(docs, [("PROLOGUE", "p.html")]))
    assert labels(result["entries"]) == ["PROLOGUE", *ROMAN[:6], "EPILOGUE"]
    assert all(not e["children"] for e in result["entries"])


def test_own_list_is_kept_when_already_as_good():
    old = [(f"Chapter {k + 1}: as printed", f"c{k:02d}.html#c{k}") for k in range(9)]
    old.append(("Afterword", "c09.html#c9"))
    result = plan(make(chapters(), old))
    assert result["decision"] == "keep"
    assert result["reason_codes"] == ["existing_matches_headings"]
    assert result["entries"] == []


def test_own_list_with_junk_label_is_rebuilt_even_when_the_count_matches():
    old = [(f"Chapter {k + 1}", f"c{k:02d}.html") for k in range(9)] + [
        ("index_split_009", "c09.html")
    ]
    result = plan(make(chapters(), old))
    assert result["decision"] == "propose"
    assert result["entries"][-1]["label"] == "Chapter 10"


def test_own_list_with_repeated_labels_is_rebuilt():
    old = [("Chapter", f"c{k:02d}.html") for k in range(10)]
    result = plan(make(chapters(), old))
    assert labels(result["entries"]) == [f"Chapter {k + 1}" for k in range(10)]


def test_long_book_without_headings_keeps_a_clean_own_list():
    docs = {f"a{k}.html": page(prose(5000)) for k in range(5)}
    old = [(f"Part {k + 1}", f"a{k}.html") for k in range(5)]
    result = plan(make(docs, old))
    assert result["decision"] == "keep"
    assert result["reason_codes"] == ["rebuild_too_short"]


def test_a_repeated_heading_on_a_split_continuation_file_is_listed_once():
    docs = {
        "a.html": page('<h2 id="a">Chapter One</h2>' + prose(300)),
        "a2.html": page('<h2 id="a2">Chapter One</h2>' + prose(300)),
        "b.html": page('<h2 id="b">Chapter Two</h2>' + prose(300)),
    }
    assert labels(plan(make(docs, [("Start", "a.html")]))["entries"]) == [
        "Chapter One",
        "Chapter Two",
    ]


def test_file_name_and_placeholder_headings_are_left_out():
    docs = chapters(4)
    docs["x.html"] = page('<h2 id="x">index_split_004</h2>' + prose(50))
    docs["y.html"] = page('<h2 id="y">Start</h2>' + prose(50))
    result = plan(make(docs, [("Start", "c00.html")]))
    assert labels(result["entries"]) == [f"Chapter {k + 1}" for k in range(4)]


def test_a_heading_deep_in_a_file_requires_an_anchor_not_the_file_start():
    docs = chapters(3)
    docs["z.html"] = page(prose(800) + "<h2>Chapter 4</h2>" + prose(300))
    result = plan(make(docs, [("Start", "c00.html")]))
    last = result["entries"][-1]
    assert last["label"] == "Chapter 4"
    assert last["requires_anchor"] is True and last["fragment"] is None


def test_a_heading_with_an_empty_id_attribute_is_never_given_a_second_one():
    docs = chapters(3)
    docs["z.html"] = page(prose(800) + '<h2 id="">Chapter 4</h2>' + prose(300))
    result = plan(make(docs, [("Start", "c00.html")]))
    assert labels(result["entries"]) == ["Chapter 1", "Chapter 2", "Chapter 3"]


def test_a_bare_number_opening_a_chapter_file_is_a_heading():
    docs = {
        f"c{k}.html": page(f'<p class="x" id="n{k}">{w}</p>{prose(300)}')
        for k, w in enumerate(WORDS[:4])
    }
    assert labels(plan(make(docs, [("Start", "c0.html")]))["entries"]) == WORDS[:4]


def test_a_rebuild_equal_to_the_own_list_is_kept_without_changes():
    # LF rebuilds a one-entry story list to the same entry; nothing would change here.
    data = make(
        {"book.html": page('<h1 id="calibre_toc_1">A Synthetic Story</h1>' + prose(3000))},
        [("A Synthetic Story", "book.html")],
    )
    result = plan(data)
    assert result["decision"] == "keep"
    assert result["reason_codes"] == ["existing_matches_rebuild"]


def test_a_start_placeholder_for_a_short_story_becomes_its_title_heading():
    data = make(
        {
            "title.html": page('<p><img src="cover.jpg" alt=""/></p>'),
            "book.html": page('<h1 id="calibre_toc_1">Synthetic Tale</h1>' + prose(3000)),
        },
        [("Start", "title.html")],
        media=["cover.jpg"],
    )
    result = plan(data)
    assert result["decision"] == "propose"
    assert labels(result["entries"]) == ["Synthetic Tale"]


def test_a_short_story_without_headings_gets_one_entry_for_its_title():
    data = make({"book.html": page(prose(3000))}, [], title="A Quiet Synthetic Tale")
    result = plan(data)
    assert result["decision"] == "propose"
    assert result["reason_codes"] == ["single_story"]
    entry = result["entries"][0]
    assert (entry["label"], entry["origin"], entry["fragment"]) == (
        "A Quiet Synthetic Tale",
        "book_title",
        None,
    )
    assert entry["label_source"]["path"] == "book.opf"


def test_an_author_byline_heading_is_not_a_chapter():
    docs = {
        f"s{k}.html": page(
            f'<h1 id="t{k}">Story Title {WORDS[k]}</h1><h2 id="b{k}">Fixture Author</h2>'
            + prose(400)
        )
        for k in range(3)
    }
    result = plan(make(docs, [("Start", "s0.html")], creator="Fixture Author"))
    assert labels(result["entries"]) == [f"Story Title {w}" for w in WORDS[:3]]


def test_numbering_gaps_in_a_long_book_are_held():
    # A gap between neighbouring pages is the book's own numbering; one across pages is not.
    docs = {
        f"c{k}.html": page(f'<h2 id="c{k}">Chapter {n}</h2>{prose(4000)}' if n else prose(4000))
        for k, n in enumerate([1, 2, 3, 0, 9, 10, 11])
    }
    result = plan(make(docs, [("Start", "c0.html")]))
    assert result["decision"] == "held"
    assert result["reason_codes"] == ["numbering_unsettled"]
    assert result["problems"]


def test_a_huge_section_without_entries_is_held():
    docs = {f"c{k}.html": page(f'<h2 id="c{k}">Chapter {k + 1}</h2>{prose(400)}') for k in range(3)}
    docs["c3.html"] = page('<h2 id="c3">Chapter 4</h2>' + prose(41000))
    result = plan(make(docs, [("Start", "c0.html")]))
    assert result["decision"] == "held"
    assert result["reason_codes"] == ["missed_chapters"]


def test_printed_contents_links_rebuild_a_book_without_headings():
    docs = {
        "toc.html": page(
            "<h1>Contents</h1>"
            + "".join(f'<p><a href="s{k}.html#a{k}">Synthetic Story {k}</a></p>' for k in range(4))
        )
    }
    for k in range(4):
        docs[f"s{k}.html"] = page(f'<p id="a{k}">{prose(6000)[3:-4]}</p>')
    result = plan(make(docs, [("Start", "toc.html")]))
    assert result["decision"] == "propose"
    assert result["reason_codes"] == ["printed_contents"]
    assert labels(result["entries"]) == [f"Synthetic Story {k}" for k in range(4)]
    assert result["entries"][0]["origin"] == "printed_link"
    assert result["entries"][0]["label_source"]["path"] == "toc.html"


def test_plan_measures_are_reported_and_planning_is_deterministic():
    data = brothers()
    first, second = plan(data), plan(data)
    assert first == second
    assert first["measures"] == {
        "existing": 8,
        "headings": 35,
        "linked": 35,
        "entries": 35,
        "words": first["measures"]["words"],
    }


def test_a_part_title_ending_in_an_ellipsis_or_quote_joins_its_part():
    # LF joins "PART ONE" with the short line under it whatever its last character (1824, 560).
    subtitles = ["TERROR IS THEIR HARBINGER…", "‘FOR THE EMPEROR!’", "THE LAST GATE"]
    docs, old = {}, []
    for n, sub in enumerate(subtitles):
        docs[f"p{n}.html"] = page(f'<h1 id="p{n}">PART {WORDS[n]}</h1><p>{sub}</p>')
        docs[f"c{n}.html"] = page(
            "".join(f'<h2 id="c{n}_{k}">{ROMAN[k]}</h2>{prose(400)}' for k in range(3))
        )
        old.append((f"PART {WORDS[n]}", f"p{n}.html"))
    result = plan(make(docs, old))
    assert labels(result["entries"]) == [
        "PART ONE: TERROR IS THEIR HARBINGER…",
        "PART TWO: ‘FOR THE EMPEROR!’",
        "PART THREE: THE LAST GATE",
    ]
    assert result["entries"][0]["origin"] == "joined_label"


def test_a_page_opening_with_a_link_does_not_vote_for_a_title_style():
    # Two long pages opening with a styled line are not three (999): LF counts the first line.
    docs = {
        "a.html": page(
            '<p class="lead"><a href="b.html">Store link</a></p>'
            '<p class="lead">Sons of the Moon</p>' + prose(300)
        ),
        "b.html": page('<p class="lead">The Grey Shore</p>' + prose(300)),
        "c.html": page('<p class="lead">Under Iron Skies</p>' + prose(300)),
    }
    result = plan(make(docs, [("Start", "a.html")], title="Synthetic Tale"))
    assert result["reason_codes"] == ["single_story"]
    docs["a.html"] = page('<p class="lead">Sons of the Moon</p>' + prose(300))
    result = plan(make(docs, [("Start", "a.html")], title="Synthetic Tale"))
    assert labels(result["entries"]) == ["Sons of the Moon", "The Grey Shore", "Under Iron Skies"]


def test_printed_links_opening_the_same_spot_are_one_entry():
    # "Macrocontent 001" and "Microcontent 01" open the same paragraph (305): one entry.
    links = "".join(
        f'<p><a href="s{k}.html#m{k}">Macro {k + 1}</a></p>'
        f'<p><a href="s{k}.html#n{k}">Micro {k + 1}</a></p>'
        for k in range(3)
    )
    docs = {"toc.html": page("<h1>Contents</h1>" + links)}
    for k in range(3):
        docs[f"s{k}.html"] = page(
            f'<p><span id="m{k}"></span><span id="n{k}"></span>{prose(4000)[3:-4]}</p>'
        )
    result = plan(make(docs, [("Start", "toc.html")]))
    assert result["reason_codes"] == ["printed_contents"]
    assert labels(result["entries"]) == ["Macro 1 Micro 1", "Macro 2 Micro 2", "Macro 3 Micro 3"]


def test_prose_tagged_as_a_heading_is_read_as_the_paragraph_lf_makes_it():
    # LF demotes the prose heading first, then finds the styled epilogue on that page (757).
    docs = {
        "a.html": page('<h1 id="a">THE ASCENSION</h1>' + prose(300)),
        "b.html": page('<h1 id="b">PROLOGUE</h1>' + prose(300)),
        "c.html": page(
            "<h2>Chapter serfs assisted her to the centre of the circle formed by the "
            "others, who waited.</h2>" + prose(300) + "<p>EPILOGUE – INT. MEDICAE.</p>" + prose(200)
        ),
    }
    result = plan(make(docs, [("Start", "a.html")]))
    assert labels(result["entries"]) == ["THE ASCENSION", "PROLOGUE", "EPILOGUE – INT. MEDICAE."]
    assert result["entries"][2]["requires_anchor"] is True
    assert result["entries"][2]["origin"] == "paragraph"


def test_a_line_after_a_demoted_heading_does_not_open_its_page():
    # LF's demoted prose heading becomes the page's first paragraph, so the numbered-looking
    # line under it is not a chapter opening its page (358).
    docs = {
        f"c{k}.html": page(f'<h1 id="c{k}">Chapter {k + 1}</h1>' + prose(300)) for k in range(3)
    }
    docs["x.html"] = page(
        "<h2>The Final Compliance of</h2><p>Sixty-Three Fourteen</p>" + prose(300)
    )
    result = plan(make(docs, [("Start", "c0.html")]))
    assert labels(result["entries"]) == ["Chapter 1", "Chapter 2", "Chapter 3"]
