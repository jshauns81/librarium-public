import hashlib
import io
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import close_old_connections, connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from librarium import artifacts, content_evidence, file_inspections
from librarium.models import Job
from librarium.services import advance, cancel, claim
from test_epub_inspection import archive


@pytest.fixture
def store(tmp_path, settings, transactional_db):
    # Heartbeats use an independent connection and must see committed jobs.
    # Restore the current schema after tests of historical migrations.
    MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
    root = tmp_path / "artifacts"
    root.mkdir(mode=0o700)
    settings.LIBRARIUM_ARTIFACT_DIR = str(root)
    return root


def enqueue(data=None, key=None, name="Uploaded EPUB.epub"):
    data = archive() if data is None else data
    return file_inspections.enqueue(
        io.BytesIO(data), key or uuid.uuid4(), hashlib.sha256(data).hexdigest(), name
    )


def complete(job):
    item = claim()
    assert item.pk == job.pk
    assert advance(item.pk, item.lease_token)
    job.refresh_from_db()
    return job


def test_new_jobs_capture_the_contents_planning_policy(db, store):
    job = enqueue()
    assert job.input["source_version"] == "librarium.epub-structure.v10"
    assert job.input["policy"]["version"] == "librarium.epub-structure.v10"


@pytest.mark.parametrize("control", ["\x7f", "&#127;"])
@pytest.mark.parametrize("field", ["title", "credit"])
def test_unsupported_attribution_label_does_not_discard_worker_report(
    db, store, control, field, monkeypatch
):
    from test_epub_source_attribution import TITLEPAGE, parts

    renewed = threading.Event()
    renew_lease = file_inspections.renew
    inspect_source = file_inspections.inspect_isolated

    def renew(*args):
        result = renew_lease(*args)
        if result:
            renewed.set()
        return result

    def inspecting(*args):
        report = inspect_source(*args)
        assert renewed.wait(5), "The worker heartbeat must renew before publication"
        return report

    monkeypatch.setattr(file_inspections, "HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(file_inspections, "renew", renew)
    monkeypatch.setattr(file_inspections, "inspect_isolated", inspecting)
    body = (
        TITLEPAGE.replace("The ", f"The{control} ")
        if field == "title"
        else TITLEPAGE.replace("Ada Writer", f"Ada{control} Writer")
    )
    original = archive(parts(body))
    job = complete(enqueue(original))
    assert job.state == "succeeded"
    report = file_inspections.report(job)["report"]
    assert report["inspection_complete"] is True
    assert report["structural_check"] == "passed"
    assert report["source_attribution"]["status"] == "unconfirmed"
    assert report["source_attribution"]["reason"] == "unsupported_label_text"
    assert artifacts.read("source", job.target_id, len(original)) == original


def test_v7_report_refuses_changed_source_attribution_binding(db, store):
    from copy import deepcopy

    job = complete(enqueue())
    value = deepcopy(file_inspections.report(job)["report"])
    value["source_attribution"]["source_sha256"] = "0" * 64
    stored = artifacts.write_report(value)
    job.result.update(report_sha256=stored["sha256"], report_size=stored["size"])
    job.save()
    with pytest.raises(file_inspections.InspectionError, match="source attribution"):
        file_inspections.report(job)


def historical(job, value, version):
    """A current report relabelled as an older inspection, with that version's v1 evidence."""
    job.result["contents_plan"]["policy_version"] = "librarium.contents-plan.v1"
    value["contents_plan"]["inspection_policy"] = version
    value["contents_plan"]["policy_version"] = "librarium.contents-plan.v1"
    for key in ("measures", "problems"):
        value["contents_plan"].pop(key, None)
    value.pop("contents_observations", None)
    for document in value["documents"]:
        document.pop("blocks", None)
        document.pop("contents_signals", None)
        for heading in document.get("headings", []):
            heading.pop("has_id", None)
            heading.pop("only_link", None)
    if isinstance(value.get("content_evidence"), dict):
        value["content_evidence"]["policy"] = "librarium.epub-content-evidence.v1"
        value["content_evidence"].pop("empty_spine_documents", None)
    if isinstance(value.get("document_text_evidence"), dict):
        value["document_text_evidence"].update(
            policy="librarium.epub-document-text.v1",
            scope=content_evidence.HISTORICAL_DOCUMENT_TEXT_SCOPE,
        )
    return value


def test_completed_v6_retains_absence_and_pending_v6_refuses_upgrade(db, store):
    from copy import deepcopy

    from librarium.services import fingerprint

    job = complete(enqueue())
    value = deepcopy(file_inspections.report(job)["report"])
    job.input["source_version"] = "librarium.epub-structure.v6"
    job.input["policy"]["version"] = job.input["source_version"]
    job.input_fingerprint = fingerprint(job.input)
    value["policy"] = deepcopy(job.input["policy"])
    historical(job, value, job.input["source_version"])
    value.pop("source_attribution", None)
    value.pop("document_text_evidence", None)
    stored = artifacts.write_report(value)
    job.result.update(
        source_version=job.input["source_version"],
        policy=job.input["policy"],
        input_fingerprint=job.input_fingerprint,
        report_sha256=stored["sha256"],
        report_size=stored["size"],
    )
    job.save()
    assert "source_attribution" not in file_inspections.report(job)["report"]
    pending = enqueue(key=uuid.uuid4())
    pending.input["source_version"] = "librarium.epub-structure.v6"
    pending.input["policy"]["version"] = pending.input["source_version"]
    pending.input_fingerprint = fingerprint(pending.input)
    pending.save()
    assert complete(pending).state == "failed"


@pytest.mark.parametrize("field", ["package_sha256", "value", "text_only"])
def test_report_retrieval_rechecks_the_identifier_capture_inside_a_bound_artifact(db, store, field):
    from copy import deepcopy

    job = complete(enqueue())
    report = deepcopy(file_inspections.report(job)["report"])
    if field == "package_sha256":
        report["identifier_evidence"][field] = "0" * 64
    else:
        report["identifier_evidence"]["entries"][0][field] = (
            "different" if field == "value" else "true"
        )
    stored = artifacts.write_report(report)
    job.result.update(report_sha256=stored["sha256"], report_size=stored["size"])
    job.save()
    with pytest.raises(file_inspections.InspectionError, match="identifier declarations"):
        file_inspections.report(job)


@pytest.mark.parametrize(
    "version", [f"librarium.epub-structure.v{number}" for number in (1, 2, 3, 4)]
)
def test_pending_legacy_policy_is_not_silently_reinterpreted(db, store, version):
    from librarium.services import fingerprint

    job = enqueue()
    job.input["source_version"] = version
    job.input["policy"]["version"] = version
    if version.endswith(".v1"):
        job.input.pop("archive_reader", None)
    job.input_fingerprint = fingerprint(job.input)
    job.save()
    assert complete(job).state == "failed"


@pytest.mark.parametrize("version", [f"librarium.epub-structure.v{number}" for number in (1, 2, 3)])
def test_saved_legacy_report_remains_readable(db, store, version):
    from copy import deepcopy

    from librarium.services import fingerprint

    job = complete(enqueue())
    report = deepcopy(file_inspections.report(job)["report"])
    job.input["source_version"] = version
    job.input["policy"]["version"] = version
    if version.endswith(".v1"):
        job.input.pop("archive_reader", None)
    job.input_fingerprint = fingerprint(job.input)
    report["policy"] = deepcopy(job.input["policy"])
    report.pop("content_evidence", None)
    report.pop("source_attribution", None)
    report.pop("document_text_evidence", None)
    report.pop("identifier_evidence", None)
    if report.get("package"):
        report["package"].pop("byte_sha256", None)
    if version.endswith(".v1"):
        report.pop("archive_reader", None)
    report.pop("contents_plan", None)
    job.result.pop("contents_plan", None)
    for document in report.get("documents", []):
        for field in ("anchors", "body_word_count", "non_heading_word_count", "media_count"):
            document.pop(field, None)
        for item in document.get("headings", []) + document.get("links", []):
            for field in (
                "source_index",
                "word_offset",
                "non_heading_word_offset",
                "media_offset",
                "word_count",
                "ancestor_sources",
            ):
                item.pop(field, None)
            if "tag" in item:
                item.pop("ancestors", None)
            if not version.endswith(".v3"):
                item.pop("label", None)
    if not version.endswith(".v3"):
        for entry in report["navigation"]["entries"]:
            for field in ("label", "kind", "ancestors"):
                entry.pop(field, None)
    stored = artifacts.write_report(report)
    job.result.update(
        input_fingerprint=job.input_fingerprint,
        source_version=job.input["source_version"],
        policy=deepcopy(job.input["policy"]),
        report_sha256=stored["sha256"],
        report_size=stored["size"],
    )
    if version.endswith(".v1"):
        job.result.pop("archive_reader", None)
    job.save()
    preserved = {path.name: path.read_bytes() for path in store.iterdir()}
    assert file_inspections.report(job)["report"] == report
    assert {path.name: path.read_bytes() for path in store.iterdir()} == preserved
    assert "contents_plan" not in report
    assert all("anchors" not in document for document in report["documents"])
    assert all(
        ("label" in entry) == version.endswith(".v3") for entry in report["navigation"]["entries"]
    )


@pytest.mark.parametrize("binding", ["input", "result", "report"])
@pytest.mark.parametrize("version", [f"librarium.epub-structure.v{n}" for n in (2, 3, 4)])
def test_historical_native_reader_binding_remains_checked(db, store, binding, version):
    from copy import deepcopy

    from librarium.services import fingerprint

    job = complete(enqueue())
    value = deepcopy(file_inspections.report(job)["report"])
    job.input["source_version"] = version
    job.input["policy"]["version"] = version
    job.input_fingerprint = fingerprint(job.input)
    value["policy"] = deepcopy(job.input["policy"])
    value.pop("content_evidence", None)
    value.pop("source_attribution", None)
    value.pop("document_text_evidence", None)
    value.pop("identifier_evidence", None)
    value["package"].pop("byte_sha256", None)
    if version.endswith(".v4"):
        historical(job, value, version)
    else:
        value.pop("contents_plan", None)
        job.result.pop("contents_plan", None)
    stored = artifacts.write_report(value)
    job.result.update(
        source_version=version,
        policy=deepcopy(job.input["policy"]),
        input_fingerprint=job.input_fingerprint,
        report_sha256=stored["sha256"],
        report_size=stored["size"],
    )
    job.save()
    assert file_inspections.report(job)["report"] == value
    if binding == "input":
        job.input["archive_reader"]["version"] = "changed"
        job.input_fingerprint = fingerprint(job.input)
        job.result["input_fingerprint"] = job.input_fingerprint
    elif binding == "result":
        job.result["archive_reader"]["version"] = "changed"
    else:
        value["archive_reader"]["version"] = "changed"
        stored = artifacts.write_report(value)
        job.result.update(report_sha256=stored["sha256"], report_size=stored["size"])
    job.save()
    with pytest.raises(file_inspections.InspectionError):
        file_inspections.report(job)


@pytest.mark.parametrize(
    "mutation",
    [
        "absent",
        "source",
        "inspection_policy",
        "plan_policy",
        "ready",
        "decision",
        "held_partial",
        "empty_positive",
    ],
)
def test_current_report_requires_a_bound_read_only_contents_plan(db, store, mutation):
    from copy import deepcopy

    job = enqueue()
    captured = deepcopy(job.input)
    captured["source_version"] = "librarium.epub-structure.v4"
    captured["policy"]["version"] = captured["source_version"]
    value = {
        "schema_version": "librarium.epub-inspection.v1",
        "source_sha256": job.target_id,
        "expected_sha256": job.target_id,
        "policy": captured["policy"],
        "upstream": captured["upstream"],
        "archive_reader": captured["archive_reader"],
        "structural_check": "passed",
        "inspection_complete": True,
        "epubcheck": "not_run",
        "content_acceptance": "not_checked",
        "ready": False,
        "contents_plan": {
            "policy_version": "librarium.contents-plan.v1",
            "source_sha256": job.target_id,
            "inspection_policy": captured["source_version"],
            "decision": "held",
            "reason_codes": ["unsupported_structure"],
            "existing": [],
            "entries": [],
            "excluded_targets": [],
            "limitations": [],
            "ready": False,
        },
    }
    file_inspections._validate_report(value, captured)
    plan = value["contents_plan"]
    if mutation == "absent":
        value.pop("contents_plan")
    elif mutation == "source":
        plan["source_sha256"] = "f" * 64
    elif mutation == "inspection_policy":
        plan["inspection_policy"] = "librarium.epub-structure.v3"
    elif mutation == "plan_policy":
        plan["policy_version"] = "unbound"
    elif mutation == "ready":
        plan["ready"] = True
    elif mutation == "decision":
        plan["decision"] = "approved"
    elif mutation == "held_partial":
        plan["entries"] = [{"label": "Unconfirmed partial proposal"}]
    else:
        plan["decision"] = "propose"
    with pytest.raises(file_inspections.InspectionError):
        file_inspections._validate_report(value, captured)


def test_visible_contents_summary_is_bound_to_the_immutable_full_report(db, store):
    job = complete(enqueue())
    report = file_inspections.report(job)["report"]
    plan = report["contents_plan"]
    assert job.result.get("contents_plan") == {
        "policy_version": plan["policy_version"],
        "decision": plan["decision"],
        "reason_codes": plan["reason_codes"],
    }
    assert "read-only contents proposal" in job.result["scope"]
    original = artifacts.read_report(job.result["report_sha256"], job.result["report_size"])
    job.result["contents_plan"]["decision"] = "held" if plan["decision"] != "held" else "keep"
    job.save()
    with pytest.raises(file_inspections.InspectionError):
        file_inspections.report(job)
    assert artifacts.read_report(job.result["report_sha256"], job.result["report_size"]) == original


@pytest.mark.parametrize("decision", ["keep", "propose", "held"])
def test_native_worker_publishes_each_plan_disposition_with_a_bound_summary(db, store, decision):
    import test_contents_rebuild as books

    if decision == "keep":
        old = [(f"Chapter {k + 1}", f"c{k:02d}.html#c{k}") for k in range(10)]
        data = books.make(books.chapters(), old)
    elif decision == "propose":
        data = books.brothers()
    else:
        docs = {
            name: books.page(f'<h1 id="{name[0]}">{label}</h1>' + books.prose(11000))
            for name, label in (("a.html", "ONE"), ("b.html", "TWO"))
        }
        data = books.make(docs, [("Start", "a.html")])
    job = complete(enqueue(data))
    assert job.state == "succeeded"
    envelope = file_inspections.report(job)
    plan = envelope["report"]["contents_plan"]
    assert plan["decision"] == decision
    assert job.result["contents_plan"] == {
        key: plan[key] for key in ("policy_version", "decision", "reason_codes")
    }
    assert bool(plan["entries"]) == (decision == "propose")
    assert plan["source_sha256"] == job.target_id == hashlib.sha256(data).hexdigest()
    assert artifacts.read("source", job.target_id, len(data)) == data
    assert plan["ready"] is False


@pytest.mark.parametrize("data,structural", [(None, "passed"), (b"broken zip", "failed")])
def test_durable_inspection_and_full_report(db, store, data, structural):
    job = enqueue(data)
    assert job.kind == "epub" and job.work_id is None and not job.fixture_failure
    assert job.target_id == job.input["source_sha256"]
    assert len(json.dumps(job.input)) < 4096
    done = complete(job)
    assert done.state == "succeeded" and done.checkpoint == 4
    result = done.result
    assert result["read_only"] is True and result["synthetic"] is False
    assert result["structural_check"] == structural
    assert result["epubcheck"] == "not_run" and result["content_acceptance"] == "not_checked"
    assert result["ready"] is False
    assert len(json.dumps(result)) < 8192
    assert [f["name"] for f in result["findings"]] == [
        "Source integrity",
        "EPUB structure",
        "Navigation",
        "Scope of this check",
    ]
    assert all(set(f) >= {"name", "ok", "detail"} for f in result["findings"])
    report = file_inspections.report(job)
    assert report["report"]["source_sha256"] == job.target_id
    assert report["report_sha256"] == result["report_sha256"]
    assert "Unique synthetic story" not in json.dumps(job.input) + json.dumps(result)
    assert artifacts.read("source", job.target_id, job.input["source_size"]) == (
        archive() if data is None else data
    )


def test_replay_is_independent_of_storage_and_body(db, store, settings):
    key = uuid.uuid4()
    first = enqueue(key=key)
    settings.LIBRARIUM_ARTIFACT_DIR = ""
    with patch("librarium.artifacts.ingest", side_effect=AssertionError("reread")):
        assert enqueue(key=key).pk == first.pk
    with pytest.raises(file_inspections.InspectionError) as caught:
        enqueue(key=key, name="Other.epub")
    assert caught.value.status == 409
    with pytest.raises(file_inspections.InspectionError):
        enqueue(data=b"other", key=key)


def test_new_key_cannot_create_another_active_source_job(db, store):
    first = enqueue()
    with pytest.raises(file_inspections.InspectionError) as caught:
        enqueue()
    assert caught.value.status == 409
    cancel(first.pk)
    assert enqueue().pk != first.pk


@pytest.mark.parametrize("failure", ["source", "policy", "fingerprint", "runtime"])
def test_failures_are_generic_preserve_source_and_publish_no_report(db, store, failure):
    job = enqueue()
    if failure == "source":
        next(store.iterdir()).write_bytes(b"corrupt")
    elif failure == "policy":
        job.input["source_version"] = "unknown-policy"
        from librarium.services import fingerprint

        job.input_fingerprint = fingerprint(job.input)
        job.save()
    elif failure == "fingerprint":
        job.input["source_name"] = "changed"
        job.save()
    with (
        patch(
            "librarium.file_inspections.inspect_isolated",
            side_effect=RuntimeError("/private/token"),
        )
        if failure == "runtime"
        else patch("builtins.id", wraps=id)
    ):
        done = complete(job)
    assert done.state == "failed"
    assert done.result == {}
    assert "/private" not in done.message and str(store) not in done.message
    assert any(p.name.startswith("source-") for p in store.iterdir())


@pytest.mark.django_db(transaction=True)
def test_inspection_holds_no_database_lock_and_cancel_fences_publication(store):
    job = enqueue()
    captured = claim()
    from librarium.epub_inspection import inspect_bytes

    def inspecting(*args):
        assert not connection.in_atomic_block

        def cancel_elsewhere():
            close_old_connections()
            try:
                cancel(job.pk)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(1) as pool:
            pool.submit(cancel_elsewhere).result(timeout=3)
        return inspect_bytes(*args)

    with patch("librarium.file_inspections.inspect_isolated", side_effect=inspecting):
        assert not advance(job.pk, captured.lease_token)
    job.refresh_from_db()
    assert job.state == "cancelled" and job.result == {}


@pytest.mark.django_db(transaction=True)
def test_expired_and_reclaimed_workers_cannot_publish(store):
    job = enqueue()
    old = claim()
    Job.objects.filter(pk=job.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    assert not advance(job.pk, old.lease_token)
    recovered = claim()
    assert recovered.attempts == 2
    assert not advance(job.pk, old.lease_token)
    assert advance(job.pk, recovered.lease_token)
    job.refresh_from_db()
    assert job.state == "succeeded" and job.attempts == 2


@pytest.mark.django_db(transaction=True)
def test_lease_is_renewed_during_slow_inspection_and_thread_closes_connection(store):
    job = enqueue()
    item = claim()
    from librarium.epub_inspection import inspect_bytes

    original = item.lease_until

    def inspecting(*args):
        # The renewal thread gets a short interval here, without extending the worker budget.
        event = threading.Event()
        for _ in range(100):
            if Job.objects.get(pk=job.pk).lease_until > original:
                break
            event.wait(0.01)
        assert Job.objects.get(pk=job.pk).lease_until > original
        return inspect_bytes(*args)

    with (
        patch("librarium.file_inspections.HEARTBEAT_SECONDS", 0.01),
        patch("librarium.file_inspections.inspect_isolated", side_effect=inspecting),
    ):
        assert advance(job.pk, item.lease_token)
    assert not any(t.name.startswith("epub-lease-") for t in threading.enumerate())


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_equal_key_and_distinct_keys(store):
    def attempt(key):
        close_old_connections()
        try:
            return str(enqueue(key=key).pk)
        except file_inspections.InspectionError as error:
            return error.status
        finally:
            close_old_connections()

    shared = uuid.uuid4()
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(attempt, [shared] * 4))
    assert len(set(results)) == 1 and isinstance(results[0], str)
    Job.objects.update(state="cancelled")
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(attempt, [uuid.uuid4() for _ in range(4)]))
    assert sum(isinstance(r, str) for r in results) == 1
    assert results.count(409) == 3


@pytest.mark.django_db(transaction=True)
def test_management_worker_dispatches_epub(store):
    job = enqueue()
    call_command("inspection_worker", once=True)
    job.refresh_from_db()
    assert job.state == "succeeded"


def test_corrupt_report_or_source_cannot_be_read_as_evidence(db, store):
    job = complete(enqueue())
    path = next(p for p in store.iterdir() if p.name.startswith("report-"))
    path.write_bytes(b"{}")
    with pytest.raises((artifacts.ArtifactError, file_inspections.InspectionError)):
        file_inspections.report(job)


@pytest.mark.django_db(transaction=True)
def test_migration_forward_reverse_preserves_evidence(store):
    executor = MigrationExecutor(connection)
    executor.migrate([("librarium", "0004_epub_inspection_jobs")])
    job = enqueue()
    with pytest.raises(RuntimeError, match="epub"):
        MigrationExecutor(connection).migrate([("librarium", "0003_catalogue_review_jobs")])
    assert Job.objects.filter(pk=job.pk).exists()
    historical = (
        MigrationExecutor(connection)
        .loader.project_state(("librarium", "0004_epub_inspection_jobs"))
        .apps.get_model("librarium", "Job")
    )
    historical.objects.all().delete()
    MigrationExecutor(connection).migrate([("librarium", "0003_catalogue_review_jobs")])
    MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())


@pytest.mark.parametrize(
    "mutation", ["limits", "upstream", "source", "expected", "ready", "status"]
)
def test_mismatched_inspector_output_never_publishes(db, store, mutation):
    job = enqueue()
    from librarium.epub_inspection import inspect_bytes

    report = inspect_bytes(archive(), job.target_id)
    if mutation == "limits":
        report["policy"]["limits"].pop("max_members")
    elif mutation == "upstream":
        report["upstream"]["revision"] = "unknown"
    elif mutation == "source":
        report["source_sha256"] = "b" * 64
    elif mutation == "expected":
        report["expected_sha256"] = "b" * 64
    elif mutation == "ready":
        report["ready"] = True
    else:
        report["structural_check"] = "unverified"
    with patch("librarium.file_inspections.inspect_isolated", return_value=report):
        done = complete(job)
    assert done.state == "failed" and done.result == {}


def test_missing_policy_limits_cannot_fall_back_to_current_defaults(db, store):
    from librarium.services import fingerprint

    job = enqueue()
    job.input["policy"]["limits"].pop("max_members")
    job.input_fingerprint = fingerprint(job.input)
    job.save()
    assert complete(job).state == "failed"


@pytest.mark.django_db(transaction=True)
def test_lease_expiring_during_work_cannot_be_renewed_or_published(store):
    job = enqueue()
    item = claim()
    from librarium.epub_inspection import inspect_bytes

    def inspecting(*args):
        Job.objects.filter(pk=job.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
        assert not file_inspections.renew(job.pk, item.lease_token)
        return inspect_bytes(*args)

    with patch("librarium.file_inspections.inspect_isolated", side_effect=inspecting):
        assert not advance(job.pk, item.lease_token)
    job.refresh_from_db()
    assert job.result == {} and job.state == "running"
    assert complete(job).state == "succeeded"


@pytest.mark.django_db(transaction=True)
def test_artifact_reads_and_report_writes_happen_outside_transactions(store):
    job = enqueue()
    read, write = artifacts.read, artifacts.write_report

    def reading(*args):
        assert not connection.in_atomic_block
        return read(*args)

    def writing(*args):
        assert not connection.in_atomic_block
        return write(*args)

    with (
        patch("librarium.artifacts.read", side_effect=reading),
        patch("librarium.artifacts.write_report", side_effect=writing),
    ):
        assert complete(job).state == "succeeded"


def test_empty_navigation_is_not_a_positive_summary(db, store):
    from test_epub_inspection import changed

    data = archive(changed("EPUB/nav.xhtml", b'epub:type="toc"', b'epub:type="landmarks"'))
    done = complete(enqueue(data))
    assert done.state == "succeeded"
    assert done.result["structural_check"] == "passed"
    assert next(f for f in done.result["findings"] if f["name"] == "Navigation")["ok"] is False


@pytest.mark.parametrize(
    "overrides", [{"target_id": "not-a-digest"}, {"target_id": "A" * 64}, {"fixture_failure": True}]
)
def test_database_rejects_invalid_epub_targets(db, store, overrides):
    from django.db import IntegrityError, transaction

    job = enqueue()
    base = {
        "kind": "epub",
        "target_id": "b" * 64,
        "input": job.input,
        "input_fingerprint": job.input_fingerprint,
        "request_key": uuid.uuid4(),
    }
    with pytest.raises(IntegrityError), transaction.atomic():
        Job.objects.create(**(base | overrides))


@pytest.mark.parametrize("change", ["source", "policy", "upstream", "ready"])
def test_validly_hashed_report_rebound_to_other_evidence_is_refused(db, store, change):
    job = complete(enqueue())
    value = file_inspections.report(job)["report"]
    if change == "source":
        value["source_sha256"] = "b" * 64
    elif change == "policy":
        value["policy"]["version"] = "other"
    elif change == "upstream":
        value["upstream"]["revision"] = "other"
    else:
        value["ready"] = True
    stored = artifacts.write_report(value)
    job.result["report_sha256"] = stored["sha256"]
    job.result["report_size"] = stored["size"]
    job.save()
    with pytest.raises(file_inspections.InspectionError):
        file_inspections.report(job)


@pytest.mark.django_db(transaction=True)
def test_renewal_database_failure_never_publishes_and_leaves_reclaimable_job(store):
    from django.db import OperationalError
    from librarium.epub_inspection import inspect_bytes

    job = enqueue()
    item = claim()

    def inspecting(*args):
        threading.Event().wait(0.08)
        return inspect_bytes(*args)

    with (
        patch("librarium.file_inspections.HEARTBEAT_SECONDS", 0.01),
        patch("librarium.file_inspections.renew", side_effect=OperationalError("private host")),
        patch("librarium.file_inspections.inspect_isolated", side_effect=inspecting),
    ):
        assert not advance(job.pk, item.lease_token)
    job.refresh_from_db()
    assert job.state == "running" and job.result == {}
    assert not any(t.name.startswith("epub-lease-") for t in threading.enumerate())


def test_model_changes_match_declared_migration(db):
    call_command("makemigrations", check=True, dry_run=True, verbosity=0)


@pytest.mark.parametrize("mutation", ["source", "path", "resource", "count", "missing"])
def test_v8_worker_report_rechecks_document_text_capture(db, store, mutation):
    from copy import deepcopy

    data = archive()
    job = complete(enqueue(data))
    assert job.state == "succeeded"
    report = deepcopy(file_inspections.report(job)["report"])
    value = report["document_text_evidence"]
    assert value["status"] == "recorded" and len(value["documents"]) == 2
    assert artifacts.read("source", job.target_id, len(data)) == data
    if mutation == "source":
        value["source_sha256"] = "a" * 64
    elif mutation == "path":
        value["documents"][0]["path"] = "another.xhtml"
    elif mutation == "resource":
        value["documents"][0]["resource_sha256"] = "b" * 64
    elif mutation == "count":
        value["documents"][0]["text_chars"] += 1
    else:
        report.pop("document_text_evidence")
    stored = artifacts.write_report(report)
    job.result.update(report_sha256=stored["sha256"], report_size=stored["size"])
    job.save()
    with pytest.raises(file_inspections.InspectionError, match="document text"):
        file_inspections.report(job)


def test_completed_v7_retains_absence_and_pending_v7_refuses_document_text_upgrade(db, store):
    from copy import deepcopy

    from librarium.services import fingerprint

    job = complete(enqueue())
    value = deepcopy(file_inspections.report(job)["report"])
    job.input["source_version"] = "librarium.epub-structure.v7"
    job.input["policy"]["version"] = job.input["source_version"]
    job.input_fingerprint = fingerprint(job.input)
    value["policy"] = deepcopy(job.input["policy"])
    historical(job, value, job.input["source_version"])
    value.pop("document_text_evidence")
    stored = artifacts.write_report(value)
    job.result.update(
        source_version=job.input["source_version"],
        policy=job.input["policy"],
        input_fingerprint=job.input_fingerprint,
        report_sha256=stored["sha256"],
        report_size=stored["size"],
    )
    job.save()
    assert "document_text_evidence" not in file_inspections.report(job)["report"]
    pending = enqueue(key=uuid.uuid4())
    pending.input["source_version"] = "librarium.epub-structure.v7"
    pending.input["policy"]["version"] = pending.input["source_version"]
    pending.input_fingerprint = fingerprint(pending.input)
    pending.save()
    assert complete(pending).state == "failed"


@pytest.mark.parametrize(
    "target,media", [("map.svg", "image/svg+xml"), ("nav.xhtml", "application/xhtml+xml")]
)
def test_v8_nonspine_manifest_alias_keeps_worker_report_and_source(db, store, target, media):
    from test_epub_content_evidence import replaced

    addition = f'<item id="alias" href="{target}" media-type="{media}"/>'.encode()
    data = archive(replaced("EPUB/book.opf", b"</manifest>", addition + b"</manifest>"))
    job = complete(enqueue(data))
    assert job.state == "succeeded"
    report = file_inspections.report(job)["report"]
    assert report["structural_check"] == "passed"
    assert report["document_text_evidence"]["status"] == "recorded"
    assert artifacts.read("source", job.target_id, len(data)) == data


@pytest.mark.django_db(transaction=True)
def test_inspection_sandbox_refusal_records_no_verdict(store, monkeypatch, tmp_path):
    from librarium import inspection_process

    child = tmp_path / "refusing.py"
    child.write_text("import sys;sys.exit(23)")
    monkeypatch.setattr(inspection_process, "_CHILD_PATH", child)
    job = complete(enqueue())
    assert job.state == "failed"
    assert job.result == {"error_code": "sandbox_setup_failed", "ready": False}


@pytest.mark.parametrize(
    "change",
    [
        lambda plan: plan.pop("measures"),
        lambda plan: plan.update(measures={"existing": 1}),
        lambda plan: (
            plan["measures"].update(words=-1) if plan["measures"] else plan.pop("measures")
        ),
        lambda plan: plan.update(problems=["a", "b", "c", "d"]),
        lambda plan: plan.update(problems=[{"code": "x"}]),
    ],
)
def test_v10_plan_measures_and_findings_are_rechecked_on_retrieval(db, store, change):
    from copy import deepcopy

    job = complete(enqueue())
    value = deepcopy(file_inspections.report(job)["report"])
    assert value["contents_plan"]["policy_version"] == "librarium.contents-plan.v2"
    change(value["contents_plan"])
    stored = artifacts.write_report(value)
    job.result.update(report_sha256=stored["sha256"], report_size=stored["size"])
    job.save()
    with pytest.raises(file_inspections.InspectionError, match="contents plan"):
        file_inspections.report(job)
