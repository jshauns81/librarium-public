"""Actual official checker runs use only original synthetic publications."""

import hashlib
import os
from pathlib import Path

import pytest
from librarium.epubcheck_process import VALIDATION_POLICY, VALIDATOR_IDENTITY, validate_isolated
from test_epub_inspection import archive


def publication(variant="valid"):
    identifier = (
        "urn:uuid:bogus"
        if variant == "warning"
        else "urn:uuid:8c9c266a-52ab-4c45-97fe-6fc39de023c9"
    )
    modified = (
        ""
        if variant == "invalid"
        else '<meta property="dcterms:modified">2026-10-27T00:00:00Z</meta>'
    )
    story = "<p>Original synthetic publication.</p>"
    if variant == "repeated":
        story = '<p illegal="yes">Original synthetic paragraph.</p>' * 40
    return archive(
        [
            ("mimetype", b"application/epub+zip"),
            (
                "META-INF/container.xml",
                b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
            ),
            (
                "book.opf",
                (
                    '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                    f'<dc:identifier id="uid">{identifier}</dc:identifier><dc:title>Synthetic publication</dc:title><dc:language>en</dc:language>{modified}'
                    '</metadata><manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest><spine><itemref idref="chapter"/></spine></package>'
                ).encode(),
            ),
            (
                "chapter.xhtml",
                (
                    '<html xmlns="http://www.w3.org/1999/xhtml" lang="en" xml:lang="en"><head><title>Chapter 1</title></head><body><h1 id="one">Chapter 1</h1>'
                    f"{story}</body></html>"
                ).encode(),
            ),
            (
                "nav.xhtml",
                b'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en"><head><title>Contents</title></head><body><nav epub:type="toc"><h1>Contents</h1><ol><li><a href="chapter.xhtml#one">Chapter 1</a></li></ol></nav></body></html>',
            ),
        ]
    )


@pytest.fixture
def runtime(settings):
    root = Path(
        os.environ.get(
            "LIBRARIUM_EPUBCHECK_DIR",
            str(Path(__file__).resolve().parents[2] / ".local/epubcheck-5.4.0"),
        )
    )
    java = Path(os.environ.get("LIBRARIUM_JAVA", "/usr/lib/jvm/java-21-openjdk-amd64/bin/java"))
    if not (root / "epubcheck.jar").is_file() or not java.is_file():
        pytest.skip("Install the pinned EPUBCheck distribution and Java 21 for native acceptance")
    settings.LIBRARIUM_EPUBCHECK_DIR = str(root)
    settings.LIBRARIUM_JAVA = str(java)


@pytest.mark.parametrize(
    "variant,outcome,code",
    [
        ("valid", "passed", 0),
        ("invalid", "failed", 1),
        ("warning", "passed", 0),
        ("repeated", "failed", 1),
    ],
)
def test_actual_epubcheck_outcomes_preserve_sources_and_report_checker_counts(
    runtime, monkeypatch, variant, outcome, code
):
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-javaagent:/invalid/unrequested-agent.jar")
    data = publication(variant)
    before = hashlib.sha256(data).hexdigest()
    report = validate_isolated(data, before, VALIDATION_POLICY, VALIDATOR_IDENTITY)
    assert report["outcome"] == outcome
    assert report["process_exit_code"] == code
    assert report["ready"] is False
    assert report["counts"]["info"] is None
    assert report["source_sha256"] == before == hashlib.sha256(data).hexdigest()
    if variant == "valid":
        assert report["counts"]["error"] == report["counts"]["warning"] == 0
    elif variant == "warning":
        assert report["counts"]["error"] == 0
        assert report["counts"]["warning"] == 1
        assert [m["id"] for m in report["messages"]] == ["OPF-085"]
    else:
        assert report["counts"]["error"] > 0
    if variant == "repeated":
        assert report["messages_truncated"] is True
        assert all(len(m["locations"]) <= 25 for m in report["messages"])
