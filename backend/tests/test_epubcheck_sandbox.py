"""Kernel file permissions and checker behavior use only owned temporary inputs."""

import ctypes
import errno
import hashlib
import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from librarium import epubcheck_sandbox
from librarium.epubcheck_process import (
    VALIDATION_POLICY,
    VALIDATOR_IDENTITY,
    ValidationProcessError,
    validate_isolated,
)
from test_epub_inspection import archive
from test_epubcheck_native import publication
from test_epubcheck_native import runtime as runtime  # noqa: PLC0414


def epub2():
    parts = {
        "mimetype": b"application/epub+zip",
        "META-INF/container.xml": b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        "book.opf": b'<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">urn:uuid:8c9c266a-52ab-4c45-97fe-6fc39de023c9</dc:identifier><dc:title>Synthetic EPUB 2</dc:title><dc:language>en</dc:language></metadata><manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest><spine toc="ncx"><itemref idref="chapter"/></spine></package>',
        "chapter.xhtml": b'<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd"><html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter 1</title></head><body><h1 id="one">Chapter 1</h1><p>Original synthetic publication.</p></body></html>',
        "toc.ncx": b'<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN" "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd"><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta name="dtb:uid" content="urn:uuid:8c9c266a-52ab-4c45-97fe-6fc39de023c9"/><meta name="dtb:depth" content="1"/><meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head><docTitle><text>Synthetic EPUB 2</text></docTitle><navMap><navPoint id="one" playOrder="1"><navLabel><text>Chapter 1</text></navLabel><content src="chapter.xhtml#one"/></navPoint></navMap></ncx>',
    }
    return parts


def test_missing_kernel_support_is_a_hard_refusal(monkeypatch, tmp_path):
    monkeypatch.setattr(epubcheck_sandbox, "available", lambda: False)
    with pytest.raises(OSError) as error:
        epubcheck_sandbox.restrict_filesystem(Path(sys.executable), [], tmp_path)
    assert error.value.errno == errno.ENOSYS


def test_child_cannot_read_or_modify_files_outside_its_private_directory(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("Owned permission-test content")
    inside = tmp_path / "scratch"
    inside.mkdir()
    (inside / "input").write_text("Owned input")
    (inside / "link").symlink_to(outside)
    script = """import sys
from pathlib import Path
sys.path.insert(0,'backend')
from librarium.epubcheck_sandbox import restrict_filesystem
inside,outside=map(Path,sys.argv[1:])
restrict_filesystem(Path(sys.executable),[],inside)
assert (inside/'input').read_text()=='Owned input'
(inside/'output').write_text('Owned output')
for path,mode in [(outside,'r'),(outside,'w'),(inside/'link','r')]:
    try:
        with path.open(mode):pass
    except PermissionError:pass
    else:raise AssertionError('Filesystem permission was not enforced')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(inside), str(outside)],
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert outside.read_text() == "Owned permission-test content"
    assert (inside / "output").read_text() == "Owned output"


def watch(path):
    library = ctypes.CDLL(None, use_errno=True)
    library.inotify_init1.argtypes = [ctypes.c_int]
    library.inotify_init1.restype = ctypes.c_int
    library.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
    library.inotify_add_watch.restype = ctypes.c_int
    descriptor = library.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
    assert descriptor >= 0
    assert library.inotify_add_watch(descriptor, os.fsencode(path), 0x21) >= 0
    return descriptor


@pytest.mark.parametrize(
    "document,root",
    [("chapter.xhtml", "html"), ("book.opf", "package"), ("META-INF/container.xml", "container")],
)
def test_native_checker_does_not_open_external_documents(runtime, tmp_path, document, root):
    sentinel = tmp_path / "owned.dtd"
    sentinel.write_text(f"<!ELEMENT {root} ANY>")
    if document == "chapter.xhtml":
        parts = epub2()
        body = parts[document]
        body = body[body.index(b">", body.index(b"<!DOCTYPE")) + 1 :]
    else:
        with zipfile.ZipFile(io.BytesIO(publication())) as zipped:
            parts = {name: zipped.read(name) for name in zipped.namelist()}
        body = parts[document]
    parts[document] = f'<!DOCTYPE {root} SYSTEM "{sentinel.as_uri()}">'.encode() + body
    data = archive(list(parts.items()))
    descriptor = watch(sentinel)
    try:
        try:
            report = validate_isolated(
                data, hashlib.sha256(data).hexdigest(), VALIDATION_POLICY, VALIDATOR_IDENTITY
            )
            assert report["outcome"] == "failed"
            assert report["ready"] is False
        except ValidationProcessError:
            pass
        with pytest.raises(BlockingIOError):
            os.read(descriptor, 4096)
    finally:
        os.close(descriptor)


def test_canonical_epub2_dtds_still_validate_from_the_pinned_distribution(runtime):
    data = archive(list(epub2().items()))
    report = validate_isolated(
        data, hashlib.sha256(data).hexdigest(), VALIDATION_POLICY, VALIDATOR_IDENTITY
    )
    assert report["outcome"] == "passed", report["messages"]
    assert report["counts"] == {"fatal": 0, "error": 0, "warning": 0, "info": None, "usage": 0}
