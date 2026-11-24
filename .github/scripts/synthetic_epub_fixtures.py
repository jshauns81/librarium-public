"""Synthetic EPUB 3 publications for native writer proofs; no real book content."""

import io
import zipfile

OPS = "http://www.idpf.org/2007/ops"
CONTAINER = (
    '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
    '<rootfiles><rootfile full-path="OEBPS/book.opf" media-type="application/oebps-package+xml"/>'
    "</rootfiles></container>"
)


def package(files):
    """Deterministic container: stored `mimetype` first, fixed timestamps."""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, data in {"mimetype": "application/epub+zip", **files}.items():
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_STORED
            archive.writestr(entry, data if type(data) is bytes else data.encode())
    return stream.getvalue()


def page(title, body, head=""):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="{OPS}" lang="en" xml:lang="en">'
        f"<head><title>{title}</title>{head}</head><body>{body}</body></html>"
    )


def chapters(*, second_anchor=False):
    anchor = ' id="second"' if second_anchor else ""
    # Words before an unanchored heading: the second chapter has no fragment to link.
    opening = "" if second_anchor else "<p>" + " ".join(["Preceding"] * 60) + ".</p>"
    return {
        "OEBPS/first.xhtml": page(
            "Chapter 1",
            '<h1 id="first">Chapter 1</h1><p>Original synthetic lantern sentence.</p>',
        ),
        "OEBPS/second.xhtml": page(
            "Chapter 2",
            f"{opening}<h1{anchor}>Chapter 2</h1><p>Original synthetic ledger ending.</p>",
        ),
    }


def epub3(*, title, creators, complete_nav=False, date=None):
    """EPUB 3 with a non-spine nav document; an incomplete nav lists only chapter one."""
    links = '<li><a href="first.xhtml#first">Chapter 1</a></li>'
    if complete_nav:
        links += '<li><a href="second.xhtml#second">Chapter 2</a></li>'
    names = "".join(f"<dc:creator>{name}</dc:creator>" for name in creators)
    # A free-text date is an EPUBCheck warning only, never an error.
    names += f"<dc:date>{date}</dc:date>" if date else ""
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="book">urn:uuid:7d0f3b62-4c6e-4d1a-9a64-8b1c2f8f2a10</dc:identifier>'
        f"<dc:title>{title}</dc:title>{names}<dc:language>en</dc:language>"
        '<meta property="dcterms:modified">2026-01-01T00:00:00Z</meta></metadata>'
        '<manifest><item id="first" href="first.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="second" href="second.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        "</manifest>"
        '<spine><itemref idref="first"/><itemref idref="second"/></spine></package>'
    )
    nav = page("Contents", f'<nav epub:type="toc" id="toc"><h1>Contents</h1><ol>{links}</ol></nav>')
    return package(
        {
            "META-INF/container.xml": CONTAINER,
            "OEBPS/book.opf": opf,
            "OEBPS/nav.xhtml": nav,
            **chapters(second_anchor=complete_nav),
        }
    )


def sources():
    """Named synthetic originals; the title and creator differ from any catalogue record."""
    return {
        "epub3": epub3(title="Proof draft lantern", creators=["Draft Person"], date="Early 2026"),
    }
