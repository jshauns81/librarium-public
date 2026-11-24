"""Reloadable selections follow captured evidence, never titles or current mounts."""

import uuid
from copy import deepcopy

import pytest
from librarium import epub_validations
from librarium.models import Job
from librarium.services import fingerprint
from retired_history import make_delivery, make_job, make_output
from test_epub_validations import source as _source
from test_epub_validations import validation_store as _validation_store

source = _source
validation_store = _validation_store
ORIGIN = {
    "library_uuid": "synthetic-library",
    "book_id": "23",
    "inventory": "a" * 64,
    "format": "EPUB",
}


def url(job):
    return f"/api/epub-inspections/{job.pk}/workspace"


def captured_origin(job, origin=ORIGIN):
    job.input["library_origin"] = deepcopy(origin)
    job.input_fingerprint = fingerprint(job.input)
    if job.result:
        job.result["input_fingerprint"] = job.input_fingerprint
    job.save()
    return job


def test_historical_context_is_narrow_and_readable_without_mount(source, client, settings):
    original = captured_origin(source())
    settings.DIRECT_LIBRARY_ROOT = "/unavailable/synthetic-library"
    reply = client.get(url(original))
    assert reply.status_code == 200, reply.content
    value = reply.json()
    assert value["origin"] == ORIGIN
    assert value["source"]["id"] == str(original.pk)
    assert value["source"]["library_origin"] == ORIGIN
    assert value["selection"] == dict.fromkeys(("fv", "fa"))
    assert value["jobs"] == [] and "output" not in value and "delivery" not in value
    assert "input" not in value["source"] and "/unavailable" not in reply.content.decode()
    assert reply.headers["Cache-Control"] == "no-store"


def test_incoming_and_pending_context_do_not_require_a_published_report(source, client):
    original = source()
    original.state, original.result = "queued", {}
    original.save()
    reply = client.get(url(original))
    assert reply.status_code == 200 and reply.json()["origin"] is None


@pytest.mark.parametrize(
    "params",
    [{"fg": "bad"}, {"x": "1"}, {"fv": ""}, [("fv", str(uuid.uuid4())), ("fv", str(uuid.uuid4()))]],
)
def test_invalid_selection_is_not_ignored(source, client, params):
    assert client.get(url(source()), params).status_code == 400


def test_foreign_validation_same_bytes_and_title_is_refused(source, client):
    first, other = source(), source()
    validation = epub_validations.enqueue(other.pk, uuid.uuid4())
    assert first.target_id == other.target_id
    reply = client.get(url(first), {"fv": str(validation.pk)})
    assert reply.status_code == 409, reply.content
    assert str(other.pk) not in reply.content.decode()
    assert client.get(url(first), {"fv": str(uuid.uuid4())}).status_code == 404


def test_changed_source_report_and_fingerprint_are_refused(source, client):
    original = source()
    validation = epub_validations.enqueue(original.pk, uuid.uuid4())
    original.result["report_sha256"] = "f" * 64
    original.save()
    assert client.get(url(original), {"fv": str(validation.pk)}).status_code == 409
    original.input["title"] = "changed"
    original.save()
    assert client.get(url(original)).status_code == 409


def test_library_resume_is_paged_scoped_and_reports_changed_inventory(
    source, client, settings, django_assert_num_queries
):
    original = captured_origin(source())
    captured_origin(source(), {**ORIGIN, "book_id": "24"})
    captured_origin(source(), {**ORIGIN, "library_uuid": "another-library"})
    settings.DIRECT_LIBRARY_ROOT = "/unavailable/synthetic-library"
    with django_assert_num_queries(2):
        reply = client.get(
            "/api/direct-library/books/23/workspaces",
            {"library_uuid": ORIGIN["library_uuid"], "inventory": "b" * 64, "page": "1"},
        )
    assert reply.status_code == 200, reply.content
    value = reply.json()
    assert value["total"] == 1 and value["page_size"] == 20
    assert value["sources"][0]["job"]["id"] == str(original.pk)
    assert value["sources"][0]["inventory_matches"] is False


@pytest.mark.parametrize(
    "bad",
    [
        {**ORIGIN, "path": "/synthetic/private"},
        {**ORIGIN, "book_id": "../23"},
        {**ORIGIN, "format": "PDF"},
        {**ORIGIN, "inventory": "bad"},
    ],
)
def test_malformed_captured_origin_never_leaks(source, client, bad):
    original = captured_origin(source(), bad)
    assert client.get(url(original)).status_code == 409
    assert "library_origin" not in client.get(f"/api/jobs/{original.pk}").json()


def test_selection_reads_remain_bounded_and_do_not_select_latest(
    source, client, django_assert_num_queries
):
    original = source()
    for _ in range(22):
        captured_origin(source())
    with django_assert_num_queries(1):
        reply = client.get(url(original))
    assert reply.status_code == 200
    assert not any(reply.json()["selection"].values())
    with django_assert_num_queries(2):
        page = client.get(
            "/api/direct-library/books/23/workspaces",
            {"library_uuid": ORIGIN["library_uuid"], "inventory": ORIGIN["inventory"], "page": "2"},
        )
    assert page.status_code == 200 and page.json()["total"] == 22
    assert len(page.json()["sources"]) == 2


def test_original_historical_policy_context_remains_available(source, client):
    original = source()
    original.input["source_version"] = "librarium.epub-structure.v1"
    original.input["policy"]["version"] = original.input["source_version"]
    original.input_fingerprint = fingerprint(original.input)
    original.result.update(
        input_fingerprint=original.input_fingerprint,
        source_version=original.input["source_version"],
        policy=original.input["policy"],
    )
    original.save()
    assert client.get(url(original)).status_code == 200


def historical_assessment(original, comparison=None):
    from librarium import library_check_jobs
    from librarium.models import LibraryReconciliation

    pin = comparison or {"work": "synthetic-work", "version": "2026.10.30.1", "sha256": "c" * 64}
    saved = LibraryReconciliation.objects.create(
        request_key=uuid.uuid4(),
        catalogue_version=pin["version"],
        catalogue_sha256=pin["sha256"],
        report={},
    )
    job = library_check_jobs.enqueue(
        "book_assessment",
        {
            "version": pin["version"],
            "sha256": pin["sha256"],
            "catalogue_work_id": pin["work"],
            "source_sha256": original.target_id,
            "report_sha256": original.result["report_sha256"],
            "reconciliation": str(saved.pk),
        },
        str(uuid.uuid4()),
        source_id=original.pk,
    )
    job.input["engine_policy"] = "librarium.book-assessment.v5"
    job.input_fingerprint = fingerprint(job.input)
    job.result = {
        "schema_version": "librarium.book-assessment.v5",
        "policy_version": "librarium.book-assessment.v5",
        "input_fingerprint": job.input_fingerprint,
        "job_id": str(original.pk),
        "source_sha256": original.target_id,
        "report_sha256": original.result["report_sha256"],
        "catalogue": {"version": pin["version"], "sha256": pin["sha256"]},
        "reconciliation_key": str(saved.pk),
        "file_work_identity": {"status": "unconfirmed", "work_id": pin["work"]},
        "edition_identity": {"status": "unconfirmed"},
        "duplicates": {"status": "not_assessed"},
        "current_library_bytes": {"status": "not_checked"},
        "inventory": {"token": "9" * 64, "library_uuid": "synthetic-library"},
        "assessed_at": "2026-11-01T12:00:00Z",
        "observation": "historical",
        "blockers": [
            "file_work_identity_not_assessed",
            "duplicates_not_assessed",
            "writer_approval_required",
        ],
        "ready": False,
        "correction_admission": "held",
    }
    job.result["result_fingerprint"] = fingerprint(job.result)
    job.state = "succeeded"
    job.save()
    library_check_jobs.assessment_report(job)
    return job


def test_null_library_identity_keeps_preserved_workspace_and_resolve_available(source, client):
    original = captured_origin(source(), {**ORIGIN, "library_uuid": None})
    reply = client.get(url(original))
    assert reply.status_code == 200, reply.content
    assert reply.json()["origin"] == {**ORIGIN, "library_uuid": None}
    assert reply.json()["source"]["library_origin"]["library_uuid"] is None
    resolved = client.get("/api/book-workspaces/resolve", {"job": str(original.pk)})
    assert resolved.status_code == 200, resolved.content
    assert resolved.json()["source_job_id"] == str(original.pk)


@pytest.mark.parametrize("unavailable", ["tampered", "unsupported"])
def test_invalid_resume_row_does_not_hide_valid_history(
    source, client, django_assert_num_queries, unavailable
):
    good = captured_origin(source())
    invalid = captured_origin(source())
    invalid.input["source_version"] = "unsupported-future-inspection"
    if unavailable == "unsupported":
        invalid.input["policy"]["version"] = invalid.input["source_version"]
        invalid.input_fingerprint = fingerprint(invalid.input)
        invalid.result.update(
            input_fingerprint=invalid.input_fingerprint,
            source_version=invalid.input["source_version"],
            policy=invalid.input["policy"],
        )
    invalid.save()
    with django_assert_num_queries(2):
        reply = client.get(
            "/api/direct-library/books/23/workspaces",
            {"library_uuid": ORIGIN["library_uuid"], "inventory": ORIGIN["inventory"]},
        )
    assert reply.status_code == 200, reply.content
    data = reply.json()
    assert data["total"] == 2 and data["unavailable_count"] == 1
    assert [row["job"]["id"] for row in data["sources"]] == [str(good.pk)]
    assert str(invalid.pk) not in reply.content.decode()
    assert client.get(url(invalid)).status_code == 409


def test_unavailable_resume_page_keeps_counts_and_does_not_scan_to_fill_it(
    source, client, django_assert_num_queries
):
    for _ in range(21):
        captured_origin(source())
    from librarium.models import Job

    newest = Job.objects.filter(kind="epub").order_by("-created_at", "-id")[:20]
    invalid_ids = list(newest.values_list("pk", flat=True))
    Job.objects.filter(pk__in=invalid_ids).update(input_fingerprint="f" * 64)
    params = {"library_uuid": ORIGIN["library_uuid"], "inventory": ORIGIN["inventory"]}
    with django_assert_num_queries(2):
        reply = client.get("/api/direct-library/books/23/workspaces", params)
    assert reply.status_code == 200, reply.content
    assert reply.json()["total"] == 21 and reply.json()["unavailable_count"] == 20
    assert reply.json()["sources"] == []
    with django_assert_num_queries(2):
        second = client.get("/api/direct-library/books/23/workspaces", {**params, "page": "2"})
    assert second.status_code == 200
    assert second.json()["total"] == 21 and second.json()["unavailable_count"] == 0
    assert len(second.json()["sources"]) == 1


RETIRED_PINS = ("fg", "fo", "fov", "faj", "fda", "fdp", "fd", "fdj")
RESOLVE = "/api/book-workspaces/resolve"
OPERATOR = {"REMOTE_USER": "synthetic-operator"}


def retired_job(kind, original, *, assessment=None, state="succeeded", **captured):
    """A stored request of retired work, bound to a preserved inspection."""
    intent = {
        "source_job_id": str(original.pk),
        "source_sha256": original.target_id,
        "report_sha256": original.result["report_sha256"],
        "assessment": str(assessment.pk) if assessment else None,
    }
    value = {
        "intent": intent,
        "source_job_id": str(original.pk),
        "title": "synthetic",
        "source_version": "retired",
        **captured,
    }
    return Job.objects.create(
        kind=kind,
        target_id=fingerprint(intent),
        request_key=uuid.uuid4(),
        input=value,
        input_fingerprint=fingerprint(value),
        state=state,
    )


def test_a_saved_route_naming_retired_selections_resolves_to_the_inspection(source, client):
    original = source()
    reply = client.get(url(original), {pin: str(uuid.uuid4()) for pin in RETIRED_PINS})
    assert reply.status_code == 200, reply.content
    value = reply.json()
    assert value["selection"] == dict.fromkeys(("fv", "fa"))
    assert value["jobs"] == [] and value["source"]["id"] == str(original.pk)
    assert "output" not in value and "delivery" not in value


@pytest.mark.parametrize("pin", ["faj", "fda"])
def test_a_retired_assessment_pin_becomes_the_kept_assessment(source, client, pin):
    original = source()
    assessment = historical_assessment(original)
    reply = client.get(url(original), {pin: str(assessment.pk), "fg": str(uuid.uuid4())})
    assert reply.status_code == 200, reply.content
    assert reply.json()["selection"] == {"fv": None, "fa": str(assessment.pk)}
    assert [row["id"] for row in reply.json()["jobs"]] == [str(assessment.pk)]
    kept = client.get(url(original), {"fa": str(assessment.pk), pin: str(uuid.uuid4())})
    assert kept.json()["selection"]["fa"] == str(assessment.pk)
    # A retired pin that no longer matches this inspection opens the inspection itself.
    foreign = historical_assessment(source("Another source.epub"))
    for stale in (foreign.pk, uuid.uuid4()):
        fallback = client.get(url(original), {pin: str(stale)})
        assert fallback.status_code == 200, fallback.content
        assert fallback.json()["selection"] == dict.fromkeys(("fv", "fa"))
    # An explicit assessment selection is still refused when it does not match.
    assert client.get(url(original), {"fa": str(foreign.pk)}).status_code == 409
    assert client.get(url(original), {"fa": str(uuid.uuid4())}).status_code == 404


def test_assessment_selection_is_bound_to_its_own_inspection(source, client):
    original, other = source(), source("Another source.epub")
    selected, foreign = historical_assessment(original), historical_assessment(other)
    assert client.get(url(original), {"fa": str(selected.pk)}).status_code == 200
    assert client.get(url(original), {"fa": str(foreign.pk)}).status_code == 409


@pytest.mark.parametrize("kind", ["epub_correction", "output_validation"])
def test_retired_generation_records_resolve_to_their_inspection(source, client, kind):
    original = source()
    job = retired_job(kind, original)
    reply = client.get(RESOLVE, {"job": str(job.pk)})
    assert reply.status_code == 200, reply.content
    assert reply.json()["source_job_id"] == str(original.pk)
    assert reply.json()["selection"] == dict.fromkeys(("fv", "fa"))


def test_a_retired_correction_resolves_to_its_assessment_when_that_still_matches(source, client):
    original = source()
    assessment = historical_assessment(original)
    job = retired_job("epub_correction", original, assessment=assessment)
    reply = client.get(RESOLVE, {"job": str(job.pk)})
    assert reply.status_code == 200, reply.content
    assert reply.json()["selection"] == {"fv": None, "fa": str(assessment.pk)}
    foreign = historical_assessment(source("Another source.epub"))
    stale = retired_job("epub_correction", original, assessment=foreign)
    fallback = client.get(RESOLVE, {"job": str(stale.pk)})
    assert fallback.status_code == 200, fallback.content
    assert fallback.json()["selection"] == dict.fromkeys(("fv", "fa"))


def test_retired_delivery_records_resolve_for_any_session(source, client):
    original = source()
    output, parts = make_output(original)
    delivery_job, delivery, _ = make_delivery(output, parts)
    records = [
        make_job("delivery_prepare", output.pk),
        delivery_job,
        make_job("delivery_reconcile", delivery.pk),
        make_job("epub_undo", delivery.pk),
    ]
    for record in records:
        for extra in ({}, OPERATOR):
            reply = client.get(RESOLVE, {"job": str(record.pk)}, **extra)
            assert reply.status_code == 200, (record.kind, reply.content)
            assert reply.json()["source_job_id"] == str(original.pk)
            assert reply.json()["selection"] == dict.fromkeys(("fv", "fa"))


def test_retired_records_with_missing_ancestors_are_refused_not_failed(source, client):
    original = source()
    gone = retired_job("epub_correction", original)
    gone.input["source_job_id"] = str(uuid.uuid4())
    gone.input_fingerprint = fingerprint(gone.input)
    gone.save()
    assert client.get(RESOLVE, {"job": str(gone.pk)}).status_code == 404
    bare = retired_job("output_validation", original)
    bare.input.pop("source_job_id")
    bare.input["intent"].pop("source_job_id")
    bare.input_fingerprint = fingerprint(bare.input)
    bare.save()
    assert client.get(RESOLVE, {"job": str(bare.pk)}).status_code == 404
    prepare = make_job("delivery_prepare", uuid.uuid4())
    assert client.get(RESOLVE, {"job": str(prepare.pk)}).status_code == 404
    reconcile = make_job("delivery_reconcile", "not-a-uuid")
    assert client.get(RESOLVE, {"job": str(reconcile.pk)}).status_code == 400


def test_a_changed_retired_record_is_refused_as_changed(source, client):
    job = retired_job("epub_correction", source())
    job.input["title"] = "changed"
    job.save()
    reply = client.get(RESOLVE, {"job": str(job.pk)})
    assert reply.status_code == 409
    assert reply.json()["code"] == "workspace_lineage_changed"
