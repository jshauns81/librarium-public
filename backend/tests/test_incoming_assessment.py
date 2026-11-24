"""Incoming files retain their own provenance while using explicit saved coverage."""

import hashlib
import io
import uuid

import pytest
import test_book_assessment as fixtures
from django.core.management import call_command
from librarium import book_assessment, file_inspections, library_check_jobs
from librarium.models import Job
from test_file_inspections import complete, historical

library = fixtures.library
catalogue_fixture = fixtures.catalogue_fixture
artifact_store = fixtures.artifact_store
selected = fixtures.selected
pytestmark = pytest.mark.django_db


def incoming(selected, raw=None):
    raw = raw or selected.raw
    return complete(
        file_inspections.enqueue(
            io.BytesIO(raw), uuid.uuid4(), hashlib.sha256(raw).hexdigest(), "Incoming.epub"
        )
    )


def assess(selected, source, **kwargs):
    return book_assessment.assess(
        source,
        selected.pin["version"],
        selected.pin["sha256"],
        "w_fixture",
        reconciliation=selected.saved,
        **kwargs,
    )


def pin(job):
    return {
        "job_id": str(job.pk),
        "source_sha256": job.target_id,
        "report_sha256": job.result["report_sha256"],
    }


def test_incoming_has_no_invented_library_origin_and_finds_original_bytes(selected):
    source = incoming(selected)
    result = assess(selected, source)
    assert result["source_provenance"]["kind"] == "incoming_upload"
    assert result["library_origin"] is None
    assert result["current_library_bytes"]["status"] == "not_applicable"
    assert result["duplicates"]["exact_bytes"]["status"] == "found"
    assert result["duplicates"]["exact_bytes"]["books"][0]["book_id"] == "1"
    assert result["duplicates"]["same_work"]["candidates"][0]["book_id"] == "1"
    assert result["correction_admission"] == "held"
    assert "content_identity_unconfirmed" in result["blockers"]
    assert "semantic_duplicates_unconfirmed" in result["blockers"]


def test_explicit_comparisons_bind_reports_and_never_clear_semantic_duplicates(selected):
    source = incoming(selected)
    result = assess(selected, source, comparison_inspections=[pin(selected.job)])
    semantic = result["duplicates"]["content"]
    assert semantic["scope"] == "explicit_preserved_inspections"
    assert semantic["clearance"] == "unconfirmed"
    row = semantic["comparisons"][0]
    assert row["inspection"] == pin(selected.job)
    assert row["text_relation"] == "same"
    assert row["inventory_membership"] == "recorded"
    assert row["book_id"] == "1"
    assert row["declared_work"]["status"] == "supported"
    assert "possible_content_duplicates" in result["blockers"]


def test_comparison_digest_mismatch_refuses_and_no_implicit_candidates_are_selected(selected):
    source = incoming(selected)
    assert assess(selected, source)["duplicates"]["content"]["comparisons"] == []
    bad = pin(selected.job) | {"report_sha256": "0" * 64}
    with pytest.raises(book_assessment.AssessmentError, match="comparison"):
        assess(selected, source, comparison_inspections=[bad])


@pytest.mark.django_db(transaction=True)
def test_incoming_durable_worker_keeps_exact_comparison_intent_and_offline_recovery(
    selected, settings
):
    source = incoming(selected)
    value = {
        "version": selected.pin["version"],
        "sha256": selected.pin["sha256"],
        "catalogue_work_id": "w_fixture",
        "source_sha256": source.target_id,
        "report_sha256": source.result["report_sha256"],
        "reconciliation": str(selected.saved.pk),
        "comparison_inspections": [pin(selected.job)],
    }
    key = str(uuid.uuid4())
    job = library_check_jobs.enqueue("book_assessment", value, key, source_id=source.pk)
    call_command("inspection_worker", once=True)
    job.refresh_from_db()
    assert job.state == "succeeded"
    assert (
        library_check_jobs.assessment_report(job)["duplicates"]["content"]["comparisons"][0][
            "text_relation"
        ]
        == "same"
    )
    saved = library_check_jobs.assessment_report(job)
    assert saved["policy_version"] == "librarium.book-assessment.v6"
    assert (
        saved["duplicates"]["content"]["comparisons"][0]["document_text_overlap"][
            "matched_documents"
        ]
        == 2
    )
    settings.DIRECT_LIBRARY_ROOT = ""
    settings.LIBRARIUM_CATALOGUE_DIR = ""
    assert (
        library_check_jobs.enqueue("book_assessment", value, key, source_id=source.pk).pk == job.pk
    )
    assert Job.objects.filter(kind="book_assessment").count() == 1


@pytest.mark.parametrize(
    "value",
    [None, {}, [{}], [{"job_id": "latest", "source_sha256": "a" * 64, "report_sha256": "a" * 64}]],
)
def test_comparison_request_shape_is_strict(selected, value):
    request = {
        "version": selected.pin["version"],
        "sha256": selected.pin["sha256"],
        "catalogue_work_id": "w_fixture",
        "source_sha256": selected.job.target_id,
        "report_sha256": selected.job.result["report_sha256"],
        "reconciliation": str(selected.saved.pk),
        "comparison_inspections": value,
    }
    with pytest.raises(library_check_jobs.CheckError):
        library_check_jobs.validate_request("book_assessment", request)


def test_native_origin_from_other_library_cannot_exclude_a_copy(selected):
    selected.job.input["library_origin"]["library_uuid"] = "another-library"
    from librarium.services import fingerprint

    selected.job.input_fingerprint = fingerprint(selected.job.input)
    selected.job.result["input_fingerprint"] = selected.job.input_fingerprint
    selected.job.save()
    with pytest.raises(book_assessment.AssessmentError, match="reconciliation"):
        assess(selected, selected.job)


def test_repackaged_text_match_is_possible_evidence_under_unrelated_declarations(selected):
    from test_epub_inspection import archive, fixture_parts

    raw = archive(
        [
            (name, body.replace(b"A synthetic volume", b"Other declared title"))
            for name, body in fixture_parts()
        ]
    )
    source = incoming(selected, raw)
    result = assess(selected, source, comparison_inspections=[pin(selected.job)])
    assert result["duplicates"]["exact_bytes"]["status"] == "none_found"
    row = result["duplicates"]["content"]["comparisons"][0]
    assert row["exact_bytes"] is False
    assert row["text_relation"] == "same"
    assert result["file_work_identity"]["status"] != "supported"
    assert result["duplicates"]["content"]["clearance"] == "unconfirmed"


def test_other_formats_remain_explicitly_unconfirmed(selected):
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(selected.library / "metadata.db")) as db, db:
        db.execute("INSERT INTO data VALUES(2,1,'PDF',1,'Other')")
    fixtures.refresh(selected)
    result = assess(selected, incoming(selected))
    assert result["duplicates"]["other_formats"]["count"] == 1
    assert result["duplicates"]["other_formats"]["status"] == "unconfirmed"
    assert "other_format_duplicates_unconfirmed" in result["blockers"]


def make_historical_v5(job):
    from copy import deepcopy

    from librarium import artifacts
    from librarium.services import fingerprint

    report = deepcopy(file_inspections.report(job)["report"])
    job.input["source_version"] = "librarium.epub-structure.v5"
    job.input["policy"]["version"] = "librarium.epub-structure.v5"
    job.input_fingerprint = fingerprint(job.input)
    report["policy"] = deepcopy(job.input["policy"])
    historical(job, report, job.input["source_version"])
    report.pop("content_evidence")
    report.pop("source_attribution", None)
    report.pop("document_text_evidence", None)
    stored = artifacts.write_report(report)
    job.result.update(
        input_fingerprint=job.input_fingerprint,
        source_version=job.input["source_version"],
        policy=deepcopy(job.input["policy"]),
        report_sha256=stored["sha256"],
        report_size=stored["size"],
    )
    job.save()


def test_v5_reports_are_readable_but_never_supply_content_clearance(selected):
    make_historical_v5(selected.job)
    source = incoming(selected)
    result = assess(selected, source, comparison_inspections=[pin(selected.job)])
    assert result["duplicates"]["content"]["comparisons"][0]["text_relation"] == "unconfirmed"
    assert result["duplicates"]["content"]["clearance"] == "unconfirmed"
    report = file_inspections.report(selected.job)["report"]
    assert report["policy"]["version"] == "librarium.epub-structure.v5"
    assert report["contents_plan"]["policy_version"] == "librarium.contents-plan.v1"


@pytest.mark.parametrize("mutation", ["digest", "source", "count", "status", "missing"])
def test_saved_report_boundary_rejects_invalid_content_capture(selected, mutation):
    from copy import deepcopy

    from librarium import artifacts

    report = deepcopy(file_inspections.report(selected.job)["report"])
    if mutation == "missing":
        report.pop("content_evidence")
    elif mutation == "digest":
        report["content_evidence"]["text_sha256"] = "garbage"
    elif mutation == "source":
        report["content_evidence"]["source_sha256"] = "0" * 64
    elif mutation == "count":
        report["content_evidence"]["text_chars"] = True
    else:
        report["content_evidence"]["status"] = "authenticated"
    stored = artifacts.write_report(report)
    selected.job.result.update(report_sha256=stored["sha256"], report_size=stored["size"])
    selected.job.save()
    with pytest.raises(file_inspections.InspectionError, match="content evidence"):
        file_inspections.report(selected.job)


def test_identical_metadata_with_changed_text_does_not_clear_semantic_duplicates(selected):
    raw = selected.raw
    # Keep the selected package metadata and alter only a body word.
    import zipfile

    from test_epub_inspection import archive, fixture_parts

    with zipfile.ZipFile(io.BytesIO(raw)) as source_zip:
        parts = [(name, source_zip.read(name)) for name, _ in fixture_parts()]
    changed = archive(
        [
            (
                name,
                body.replace(
                    b"Unique synthetic story sentence.", b"A genuinely different sentence."
                ),
            )
            for name, body in parts
        ]
    )
    source = incoming(selected, changed)
    result = assess(selected, source, comparison_inspections=[pin(selected.job)])
    assert result["duplicates"]["content"]["comparisons"][0]["text_relation"] == "different"
    overlap = result["duplicates"]["content"]["comparisons"][0]["resource_overlap"]
    assert overlap["status"] == "recorded"
    assert overlap["matched_documents"] == 1
    assert overlap["relation"] == "shared_spine_resources"
    assert overlap["matches"][0]["selected"]["path"] == "EPUB/second.xhtml"
    assert result["duplicates"]["content"]["possible_count"] == 1
    assert "possible_content_duplicates" in result["blockers"]
    assert result["file_work_identity"]["status"] == "supported"
    assert "semantic_duplicates_unconfirmed" in result["blockers"]


def test_repeated_native_inspection_is_origin_evidence_not_another_duplicate(selected):
    source = complete(
        file_inspections.enqueue(
            io.BytesIO(selected.raw),
            uuid.uuid4(),
            selected.job.target_id,
            "Second native inspection.epub",
            origin=selected.job.input["library_origin"],
        )
    )
    result = assess(selected, source, comparison_inspections=[pin(selected.job)])
    assert result["duplicates"]["content"]["comparisons"][0]["text_relation"] == "same"
    assert (
        result["duplicates"]["content"]["comparisons"][0]["resource_overlap"]["matched_documents"]
        == 2
    )
    assert result["duplicates"]["content"]["possible_count"] == 0
    assert "possible_content_duplicates" not in result["blockers"]


def test_distinct_native_record_is_still_a_possible_content_duplicate(selected):
    fixtures.add_book(selected, selected.raw)
    origin = dict(selected.job.input["library_origin"], book_id="2")
    candidate = complete(
        file_inspections.enqueue(
            io.BytesIO(selected.raw),
            uuid.uuid4(),
            selected.job.target_id,
            "Distinct native.epub",
            origin=origin,
        )
    )
    result = assess(selected, selected.job, comparison_inspections=[pin(candidate)])
    assert result["duplicates"]["content"]["possible_count"] == 1
    assert result["duplicates"]["content"]["comparisons"][0]["relationship"] == "candidate"
    assert "possible_content_duplicates" in result["blockers"]


def empty_library(selected):
    from test_direct_library import update

    update(selected.library, "DELETE FROM books")
    fixtures.refresh(selected)
    assert selected.saved.report["total"] == 0
    assert selected.saved.report["books"] == []


def test_incoming_accepts_complete_empty_coverage_without_admitting_content(selected):
    source = incoming(selected)
    empty_library(selected)
    result = assess(selected, source)
    assert result["library_origin"] is None
    assert result["current_library_bytes"]["status"] == "not_applicable"
    assert result["duplicates"]["complete"] is True
    assert result["duplicates"]["epub_files"] == 0
    assert result["duplicates"]["exact_bytes"]["status"] == "none_found"
    assert result["duplicates"]["exact_bytes"]["count"] == 0
    assert result["duplicates"]["same_work"]["candidates"] == []
    assert result["duplicates"]["content"]["clearance"] == "unconfirmed"
    assert result["correction_admission"] == "held" and result["ready"] is False
    assert "content_identity_unconfirmed" in result["blockers"]
    assert "semantic_duplicates_unconfirmed" in result["blockers"]
    assert "writer_not_authorized" in result["blockers"]


def test_native_origin_still_requires_its_selected_record_in_empty_coverage(selected):
    empty_library(selected)
    with pytest.raises(book_assessment.AssessmentError) as caught:
        assess(selected, selected.job)
    assert caught.value.code == "coverage_mismatch"


def test_changed_markup_still_finds_source_text_overlap_without_semantic_clearance(selected):
    from test_epub_inspection import archive, fixture_parts

    changed = archive(
        [
            (
                name,
                body.replace(b"Unique synthetic", b"Uni<em>que</em>  synthetic")
                .replace(b"Invented ending.", b"Another ending.")
                .replace(b"<body>", b'<body class="repackaged">'),
            )
            for name, body in fixture_parts()
        ]
    )
    source = incoming(selected, changed)
    result = assess(selected, source, comparison_inspections=[pin(selected.job)])
    row = result["duplicates"]["content"]["comparisons"][0]
    assert row["exact_bytes"] is False and row["text_relation"] == "different"
    assert row["resource_overlap"]["matched_documents"] == 0
    overlap = row["document_text_overlap"]
    assert overlap["status"] == "recorded"
    assert overlap["relation"] == "shared_document_text"
    assert overlap["matched_documents"] == 1
    assert overlap["matches"][0]["selected"]["path"] == "EPUB/first.xhtml"
    assert overlap["matches"][0]["comparison"]["path"] == "EPUB/first.xhtml"
    assert result["duplicates"]["content"]["possible_count"] == 1
    assert result["policy_version"] == "librarium.book-assessment.v6"
    assert result["duplicates"]["content"]["clearance"] == "unconfirmed"
    assert {
        "possible_content_duplicates",
        "content_identity_unconfirmed",
        "semantic_duplicates_unconfirmed",
        "writer_not_authorized",
    } <= set(result["blockers"])
    assert result["correction_admission"] == "held"


@pytest.mark.django_db(transaction=True)
def test_incoming_empty_coverage_completes_through_the_durable_worker(selected):
    source = incoming(selected)
    empty_library(selected)
    value = {
        "version": selected.pin["version"],
        "sha256": selected.pin["sha256"],
        "catalogue_work_id": "w_fixture",
        "source_sha256": source.target_id,
        "report_sha256": source.result["report_sha256"],
        "reconciliation": str(selected.saved.pk),
    }
    job = library_check_jobs.enqueue(
        "book_assessment", value, str(uuid.uuid4()), source_id=source.pk
    )
    call_command("inspection_worker", once=True)
    job.refresh_from_db()
    assert job.state == "succeeded"
    result = library_check_jobs.assessment_report(job)
    assert result["reconciliation_key"] == str(selected.saved.pk)
    assert result["duplicates"]["complete"] is True
    assert result["duplicates"]["epub_files"] == 0
    assert result["correction_admission"] == "held"
