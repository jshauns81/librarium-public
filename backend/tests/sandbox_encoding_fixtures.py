"""Synthetic encoding and ZIP-name parity corpus, independent of private inputs."""

import io
import zipfile

from test_epub_inspection import archive, fixture_parts

XHTML = "http://www.w3.org/1999/xhtml"
OPF = "http://www.idpf.org/2007/opf"


def many_heading_source(count=64):
    from test_epub_inspection import page

    parts = dict(fixture_parts())
    parts["EPUB/book.opf"] = parts["EPUB/book.opf"].replace(
        b'<itemref idref="second" linear="no"/>', b""
    )
    parts["EPUB/nav.xhtml"] = page(
        '<nav epub:type="toc"><ol><li><a href="first.xhtml">Old contents</a></li></ol></nav>'
    )
    # Chapters carry real text; a page of headings with a few words each is a title list.
    parts["EPUB/first.xhtml"] = page(
        "".join(
            f"<h1>Chapter {number}</h1><p>Synthetic chapter {number} has preserved text "
            "that runs long enough to read as a real chapter.</p>"
            for number in range(1, count + 1)
        )
    )
    return archive(list(parts.items()))


def replace_part(parts, name, body):
    return [(n, body if n == name else b) for n, b in parts]


def xhtml(encoding, text_bytes):
    return (
        f'<?xml version="1.0" encoding="{encoding}"?>'.encode()
        + f'<html xmlns="{XHTML}"><body><h1 id="one">Chapter 1</h1><p>'.encode()
        + text_bytes
        + b'</p><a href="second.xhtml#two">Next</a></body></html>'
    )


def opf(encoding, title_bytes):
    body = dict(fixture_parts())["EPUB/book.opf"]
    body = body.replace(b"A synthetic volume", title_bytes)
    return f'<?xml version="1.0" encoding="{encoding}"?>'.encode() + body


def with_ncx(encoding):
    parts = fixture_parts()
    package = dict(parts)["EPUB/book.opf"]
    package = package.replace(
        b"</manifest>",
        b'<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>',
    ).replace(b"<spine>", b'<spine toc="ncx">')
    ncx = (
        (
            f'<?xml version="1.0" encoding="{encoding}"?>'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head/>'
            "<docTitle><text>T</text></docTitle><navMap>"
            '<navPoint id="p1" playOrder="1"><navLabel><text>Caf'
        ).encode()
        + b"\xe9"
        + (b'</text></navLabel><content src="first.xhtml#one"/></navPoint></navMap></ncx>')
    )
    parts = replace_part(parts, "EPUB/book.opf", package)
    return parts + [("EPUB/toc.ncx", ncx)]


class RawName(zipfile.ZipInfo):
    raw = b""

    def _encodeFilenameFlags(self):
        return self.raw, self.flag_bits & ~0x800


def raw_name_archive(raw):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as zipped:
        for name, body in fixture_parts():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            zipped.writestr(info, body)
        info = RawName("placeholder", date_time=(2026, 1, 1, 0, 0, 0))
        info.raw = raw
        zipped.writestr(info, b"opaque")
    return stream.getvalue()


base = fixture_parts()
fixtures = {
    "base": archive(),
    "many_headings": many_heading_source(),
    "many_headings_ncx": None,
    "xhtml_windows_1252": archive(
        replace_part(base, "EPUB/first.xhtml", xhtml("windows-1252", b"\x93quoted\x94 text"))
    ),
    "xhtml_iso_8859_15": archive(
        replace_part(base, "EPUB/first.xhtml", xhtml("ISO-8859-15", b"price \xa4 5"))
    ),
    "xhtml_koi8_r": archive(
        replace_part(base, "EPUB/first.xhtml", xhtml("KOI8-R", b"\xf0\xd2\xc9\xd7\xc5\xd4"))
    ),
    "xhtml_mac_roman": archive(
        replace_part(base, "EPUB/first.xhtml", xhtml("macintosh", b"caf\x8e"))
    ),
    "xhtml_utf8_sig_name": archive(
        replace_part(base, "EPUB/first.xhtml", xhtml("utf-8-sig", b"ascii only"))
    ),
    "xhtml_utf32_name": archive(
        replace_part(base, "EPUB/first.xhtml", xhtml("UTF-32", b"ascii only"))
    ),
    "xhtml_shift_jis": archive(
        replace_part(base, "EPUB/first.xhtml", xhtml("Shift_JIS", b"\x82\xa0"))
    ),
    "xhtml_latin1_alias": archive(
        replace_part(base, "EPUB/first.xhtml", xhtml("latin1", b"caf\xe9"))
    ),
    "xhtml_cp437": archive(replace_part(base, "EPUB/first.xhtml", xhtml("cp437", b"caf\x82"))),
    "xhtml_unknown": archive(
        replace_part(base, "EPUB/first.xhtml", xhtml("x-no-such-codec", b"ascii"))
    ),
    "opf_windows_1252": archive(
        replace_part(base, "EPUB/book.opf", opf("windows-1252", b"Caf\xe9 \x93title\x94"))
    ),
    "opf_iso_8859_2": archive(replace_part(base, "EPUB/book.opf", opf("ISO-8859-2", b"\xb1\xe6"))),
    "ncx_windows_1252": archive(with_ncx("windows-1252")),
    "ncx_utf8": archive(with_ncx("UTF-8")),
    "zipname_cp437_noflag": raw_name_archive(b"EPUB/caf\x82.bin"),
    "zipname_utf8_noflag": raw_name_archive("EPUB/café.bin".encode()),
    "zipname_nfd_flagged": archive(base + [("EPUB/café.bin", b"x"), ("EPUB/café.bin", b"y")]),
}


import zipfile as _z

_src = many_heading_source()
with _z.ZipFile(io.BytesIO(_src)) as _zz:
    _parts = [(i.filename, _zz.read(i)) for i in _zz.infolist()]
_d = dict(_parts)
_opf_name = next(n for n in _d if n.endswith(".opf"))
_d[_opf_name] = (
    _d[_opf_name]
    .replace(
        b"</manifest>",
        b'<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>',
    )
    .replace(b"<spine>", b'<spine toc="ncx">')
)
_parts = list(_d.items()) + [
    (
        "EPUB/toc.ncx",
        (
            b'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head/><docTitle><text>T</text></docTitle><navMap><navPoint id="p1" playOrder="1"><navLabel><text>Old</text></navLabel><content src="first.xhtml"/></navPoint></navMap></ncx>'
        ),
    )
]
fixtures["many_headings_ncx"] = archive(_parts)


fixtures["zipname_utf8_flagged"] = archive(base + [("EPUB/caf\u00e9.bin", b"opaque")])
