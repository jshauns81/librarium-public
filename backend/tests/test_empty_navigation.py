"""Empty source navigation is reported as a structural problem, never repaired."""

import hashlib
import re
from copy import deepcopy

import pytest
from epub_members import encode_members, logical
from test_epub_inspection import inspect
from test_epubcheck_native import publication
from test_epubcheck_native import runtime as runtime  # noqa: PLC0414
from test_epubcheck_sandbox import epub2


def empty_source(kind="nav", *, anchors=False):
    members = epub2() if kind == "ncx" else logical(publication())
    if kind == "both":
        members["toc.ncx"] = epub2()["toc.ncx"]
        members["book.opf"] = (
            members["book.opf"]
            .replace(
                b"</manifest>",
                b'<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/></manifest>',
            )
            .replace(b"<spine>", b'<spine toc="ncx">')
        )
    for path in list(members):
        if path == "nav.xhtml":
            members[path] = re.sub(rb"<ol>.*?</ol>", b"<ol/>", members[path])
        elif path == "toc.ncx":
            ncx = members[path][members[path].index(b"<ncx") :]
            members[path] = re.sub(rb"<navMap>.*?</navMap>", b"<navMap/>", ncx)
    if anchors:
        members["chapter.xhtml"] = members["chapter.xhtml"].replace(b' id="one"', b"")
    return encode_members(members, list(members))


@pytest.mark.parametrize("kind", ["nav", "ncx", "both"])
@pytest.mark.parametrize("anchors", [False, True])
def test_empty_navigation_is_an_error_that_fails_the_structural_check(runtime, kind, anchors):
    from librarium.epubcheck_process import VALIDATION_POLICY, VALIDATOR_IDENTITY, validate_isolated

    data = empty_source(kind, anchors=anchors)
    digest = hashlib.sha256(data).hexdigest()
    before = validate_isolated(data, digest, VALIDATION_POLICY, VALIDATOR_IDENTITY)
    assert before["outcome"] == "failed"
    report = inspect(data)
    assert report["inspection_complete"] is True
    assert report["structural_check"] == "failed"
    assert {f["severity"] for f in report["findings"] if f["code"] == "empty_navigation"} == {
        "error"
    }
    assert {"contents_plan", "contents_observations"}.isdisjoint(report)
    assert report["document_text_evidence"]["status"] == "unconfirmed"


def test_a_book_with_prose_and_no_headings_and_an_empty_navigation_still_fails():
    members = logical(empty_source())
    members["chapter.xhtml"] = re.sub(
        rb"<body>.*?</body>",
        b"<body><p>" + b"synthetic " * 26000 + b"</p></body>",
        members["chapter.xhtml"],
    )
    report = inspect(encode_members(members, list(members)))
    assert report["structural_check"] == "failed"
    assert [f["severity"] for f in report["findings"] if f["code"] == "empty_navigation"] == [
        "error"
    ]


@pytest.mark.parametrize("defect", ["resource", "xml", "target"])
def test_empty_navigation_never_clears_another_structural_error(defect):
    members = logical(empty_source())
    if defect == "resource":
        members["chapter.xhtml"] = members["chapter.xhtml"].replace(
            b"</body>", b'<img src="missing.png"/></body>'
        )
    elif defect == "xml":
        members["chapter.xhtml"] += b"<broken"
    else:
        members["nav.xhtml"] = members["nav.xhtml"].replace(
            b"<ol/>", b'<ol><li><a href="https://example.invalid/">Bad</a></li></ol>'
        )
    data = encode_members(members, list(members))
    report = inspect(data)
    assert report["structural_check"] == "failed"


def test_empty_ncx_cannot_hide_behind_a_populated_nav():
    members = logical(empty_source("both"))
    members["nav.xhtml"] = logical(publication())["nav.xhtml"]
    data = encode_members(members, list(members))
    report = inspect(data)
    from librarium.file_inspections import _summary

    assert report["structural_check"] == "failed"
    assert [f["severity"] for f in report["findings"] if f["code"] == "empty_navigation"] == [
        "error"
    ]
    summary = _summary(
        "synthetic",
        {
            "source_version": report["policy"]["version"],
            "source_sha256": report["source_sha256"],
            "policy": report["policy"],
            "upstream": report["upstream"],
            "archive_reader": report["archive_reader"],
        },
        "synthetic",
        report,
        {"sha256": "0" * 64, "size": 1},
    )
    assert next(f for f in summary["findings"] if f["name"] == "Navigation")["ok"] is False
    assert next(f for f in summary["findings"] if f["name"] == "EPUB structure")["ok"] is False
    assert "contents_plan" not in summary


def test_empty_navigation_is_inspected_by_the_real_sandboxed_child():
    from librarium.epub_inspection import InspectionPolicy
    from librarium.inspection_process import inspect_isolated

    data = empty_source("both")
    report = inspect_isolated(data, hashlib.sha256(data).hexdigest(), InspectionPolicy())
    assert report == inspect(data)
    assert report["structural_check"] == "failed"


def test_earlier_v10_empty_navigation_report_remains_readable(db, store):
    from librarium import artifacts, file_inspections
    from test_file_inspections import as_v10, complete, enqueue

    job = complete(enqueue(empty_source()))
    report = deepcopy(file_inspections.report(job)["report"])
    assert report["structural_check"] == "failed"
    # Before v11 the planner downgraded the finding to a warning when it proposed a rebuild;
    # a stored report that kept either severity is still served as written.
    report["structural_check"] = "passed"
    for finding in report["findings"]:
        if finding["code"] == "empty_navigation":
            finding["severity"] = "warning"
    as_v10(job, report)
    assert file_inspections.report(job)["report"] == report
    assert artifacts.read_report(job.result["report_sha256"], job.result["report_size"]) == report


from test_file_inspections import store as store  # noqa: PLC0414
