"""Real synthetic EPUBs bind contents decisions to the captured XML evidence."""

import hashlib
import xml.etree.ElementTree as ET

from test_epub_inspection import archive, fixture_parts, inspect, page


def omnibus_parts():
    """Two novels: a title page, then chapters, with a printed contents page in front."""
    parts = dict(fixture_parts())
    package = parts["EPUB/book.opf"].replace(b'linear="no"', b'linear="yes"')
    additions = b"".join(
        f'<item id="{name}" href="{name}.xhtml" media-type="application/xhtml+xml"/>'.encode()
        for name in ("printed", "alpha", "beta")
    )
    package = package.replace(b"</manifest>", additions + b"</manifest>")
    package = package.replace(
        b'<spine><itemref idref="first"/><itemref idref="second" linear="yes"/></spine>',
        b'<spine><itemref idref="printed"/><itemref idref="alpha"/>'
        b'<itemref idref="first"/><itemref idref="beta"/><itemref idref="second"/></spine>',
    )
    parts["EPUB/book.opf"] = package
    story = "<p>" + " ".join(["invented"] * 200) + ".</p>"
    parts["EPUB/alpha.xhtml"] = page('<h1 id="alpha">Alpha</h1>')
    parts["EPUB/beta.xhtml"] = page('<h1 id="beta">Beta</h1>')
    parts["EPUB/first.xhtml"] = page(
        "".join(f'<h2 id="a{n}">Chapter {n}</h2>{story}' for n in range(1, 6))
    )
    parts["EPUB/second.xhtml"] = page(
        "".join(f'<h2 id="b{n}">Chapter {n}</h2>{story}' for n in range(1, 6))
    )
    parts["EPUB/nav.xhtml"] = page(
        '<nav epub:type="toc"><ol><li><a href="alpha.xhtml#alpha">Alpha</a></li>'
        '<li><a href="beta.xhtml#beta">Beta</a></li></ol></nav>'
    )
    printed = "".join(
        f'<li><a href="{path}.xhtml#{ident}">{label}</a></li>'
        for path, ident, label in (("first", "a1", "Alpha"), ("second", "b1", "Beta"))
    )
    parts["EPUB/printed.xhtml"] = page(f"<h1>Contents</h1><ol>{printed}</ol>")
    return list(parts.items())


def test_novel_titles_hold_their_chapters_without_changing_the_source():
    data = archive(omnibus_parts())
    before = hashlib.sha256(data).hexdigest()
    report = inspect(data)
    plan = report["contents_plan"]
    assert report["structural_check"] == "passed"
    assert plan["decision"] == "propose", plan["reason_codes"]
    assert [entry["label"] for entry in plan["entries"]] == ["Alpha", "Beta"]
    for group, prefix in zip(plan["entries"], "ab", strict=True):
        assert [c["label"] for c in group["children"]] == [f"Chapter {n}" for n in range(1, 6)]
        assert [c["fragment"] for c in group["children"]] == [f"{prefix}{n}" for n in range(1, 6)]
    assert plan["ready"] is False
    assert hashlib.sha256(data).hexdigest() == before == plan["source_sha256"]


def test_every_label_source_is_the_recorded_heading_node():
    parts = dict(omnibus_parts())
    plan = inspect(archive(list(parts.items())))["contents_plan"]

    def walk(entries):
        for entry in entries:
            yield entry
            yield from walk(entry["children"])

    for entry in walk(plan["entries"]):
        locator = entry["label_source"]
        body = parts[locator["path"]]
        assert locator["document_sha256"] == hashlib.sha256(body).hexdigest()
        node = list(ET.fromstring(body).iter())[locator["source_index"]]
        assert node.tag.rsplit("}", 1)[-1] in {"h1", "h2"}
        assert "".join(node.itertext()) == entry["label"]


def test_existing_blank_navigation_cannot_be_described_as_sound():
    parts = dict(fixture_parts())
    parts["EPUB/book.opf"] = parts["EPUB/book.opf"].replace(b'linear="no"', b'linear="yes"')
    parts["EPUB/nav.xhtml"] = page(
        '<nav epub:type="toc"><ol><li><a href="first.xhtml#one"/></li>'
        '<li><a href="second.xhtml#two"/></li></ol></nav>'
    )
    plan = inspect(archive(list(parts.items())))["contents_plan"]
    assert plan["decision"] != "keep", plan


def test_media_only_chapter_is_included_in_a_missing_navigation_proposal():
    parts = dict(fixture_parts())
    parts["EPUB/book.opf"] = (
        parts["EPUB/book.opf"]
        .replace(b'linear="no"', b'linear="yes"')
        .replace(b'properties="nav"', b"")
    )
    parts["EPUB/second.xhtml"] = page('<h1 id="two">Chapter 2</h1><img src="map.svg#map"/>')
    plan = inspect(archive(list(parts.items())))["contents_plan"]
    assert plan["decision"] == "propose", plan
    assert [entry["label"] for entry in plan["entries"]] == ["Chapter 1", "Chapter 2"]


def test_a_contents_section_and_the_chapters_after_it_in_one_file():
    parts = dict(fixture_parts())
    parts["EPUB/book.opf"] = parts["EPUB/book.opf"].replace(
        b'<spine><itemref idref="first"/><itemref idref="second" linear="no"/></spine>',
        b'<spine><itemref idref="first"/></spine>',
    )
    story = "<p>" + " ".join(["synthetic"] * 120) + ".</p>"
    links = "".join(f'<li><a href="#c{n}">Chapter {n}</a></li>' for n in range(1, 4))
    chapters = "".join(f'<h1 id="c{n}">Chapter {n}</h1>{story}' for n in range(1, 4))
    parts["EPUB/first.xhtml"] = page(f"<h1>Contents</h1><ol>{links}</ol>{chapters}")
    parts["EPUB/nav.xhtml"] = page(
        '<nav epub:type="toc"><ol><li><a href="first.xhtml#c1">Chapter 1</a></li></ol></nav>'
    )
    plan = inspect(archive(list(parts.items())))["contents_plan"]
    assert plan["decision"] == "propose", plan
    assert [entry["label"] for entry in plan["entries"]] == ["Chapter 1", "Chapter 2", "Chapter 3"]
    assert [entry["fragment"] for entry in plan["entries"]] == ["c1", "c2", "c3"]
