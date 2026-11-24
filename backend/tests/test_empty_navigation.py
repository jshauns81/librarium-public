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
def test_empty_navigation_is_a_reported_warning_with_a_contents_proposal(runtime, kind, anchors):
    from librarium.epubcheck_process import VALIDATION_POLICY, VALIDATOR_IDENTITY, validate_isolated

    data = empty_source(kind, anchors=anchors)
    digest = hashlib.sha256(data).hexdigest()
    before = validate_isolated(data, digest, VALIDATION_POLICY, VALIDATOR_IDENTITY)
    assert before["outcome"] == "failed"
    report = inspect(data)
    assert report["contents_plan"]["decision"] == "propose"
    assert report["structural_check"] == "passed"
    assert {f["severity"] for f in report["findings"] if f["code"] == "empty_navigation"} == {
        "warning"
    }
    assert report["document_text_evidence"]["status"] == "recorded"
    from librarium.contents_planning import contents_plan

    assert contents_plan(report) == report["contents_plan"]


def test_empty_navigation_without_a_plan_stays_held():
    members = logical(empty_source())
    members["chapter.xhtml"] = re.sub(
        rb"<body>.*?</body>",
        b"<body><p>" + b"synthetic " * 26000 + b"</p></body>",
        members["chapter.xhtml"],
    )
    data = encode_members(members, list(members))
    report = inspect(data)
    assert report["contents_plan"]["decision"] == "held"
    assert report["contents_plan"]["reason_codes"] == ["no_chapter_headings"]
    assert report["structural_check"] == "failed"
    assert report["document_text_evidence"]["status"] == "unconfirmed"


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
    from librarium.contents_planning import contents_plan
    from librarium.file_inspections import _summary

    assert report["contents_plan"]["decision"] == "propose"
    assert contents_plan(report) == report["contents_plan"]
    assert report["structural_check"] == "passed"
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


def test_empty_navigation_with_incomplete_budget_evidence_stays_held():
    from librarium.epub_inspection import InspectionPolicy

    data = empty_source()
    report = inspect(data, policy=InspectionPolicy(max_output_bytes=6500))
    assert report["inspection_complete"] is True
    assert report["structural_check"] == "failed"
    assert report["contents_plan"]["decision"] == "held"
    assert report["contents_plan"]["reason_codes"] == ["contents_evidence_unavailable"]
    assert (
        next(f for f in report["findings"] if f["code"] == "empty_navigation")["severity"]
        == "error"
    )
    assert report["document_text_evidence"]["status"] == "unconfirmed"


def test_empty_navigation_is_inspected_by_the_real_sandboxed_child():
    from librarium.epub_inspection import InspectionPolicy
    from librarium.inspection_process import inspect_isolated

    data = empty_source("both")
    report = inspect_isolated(data, hashlib.sha256(data).hexdigest(), InspectionPolicy())
    assert report == inspect(data)
    assert report["contents_plan"]["decision"] == "propose"


def test_earlier_v10_empty_navigation_report_remains_readable(db, store):
    from librarium import artifacts, file_inspections
    from test_file_inspections import complete, enqueue

    job = complete(enqueue(empty_source()))
    report = deepcopy(inspect(empty_source()))
    report["structural_check"] = "failed"
    for finding in report["findings"]:
        if finding["code"] == "empty_navigation":
            finding["severity"] = "error"
    from librarium.content_evidence import unconfirmed, unconfirmed_document_text
    from librarium.source_attribution import unconfirmed as attribution_unconfirmed

    report["content_evidence"] = unconfirmed(report["source_sha256"], "inspection_failed")
    report["document_text_evidence"] = unconfirmed_document_text(
        report["source_sha256"], "inspection_failed"
    )
    report["source_attribution"] = attribution_unconfirmed(
        report["source_sha256"], "inspection_failed"
    )
    file_inspections._validate_report(report, job.input)
    stored = artifacts.write_report(report)
    job.result = file_inspections._summary(
        str(job.pk), job.input, job.input_fingerprint, report, stored
    )
    job.save(update_fields=["result"])
    assert file_inspections.report(job)["report"] == report


from test_file_inspections import store as store  # noqa: PLC0414
