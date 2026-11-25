"""Only synthetic files and catalogues cross the read-only comparison boundary."""

import hashlib
import json
import sqlite3
import threading
from contextlib import closing
from copy import deepcopy
from html import escape

import pytest
import test_catalogue
import test_file_inspections
from librarium import artifacts, file_inspections
from librarium.models import Job
from test_catalogue import pin
from test_epub_inspection import archive, fixture_parts
from test_file_inspections import complete, enqueue

catalogue_fixture = test_catalogue.catalogue
artifact_store = test_file_inspections.store


@pytest.fixture
def comparison(transactional_db, client, catalogue_fixture, artifact_store):
    # The lease heartbeat needs committed jobs on its separate connection.
    _, path = catalogue_fixture
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE work SET title='A synthetic volume' WHERE id='w_fixture'")
        db.execute("UPDATE author SET name='Josh Reynolds' WHERE id=1")
        db.execute("INSERT INTO author_alias VALUES (1,'Joshua Reynolds')")

    def run(creators=("Joshua Reynolds",), titles=("A synthetic volume",), **query):
        metadata = "".join(f"<dc:title>{escape(t)}</dc:title>" for t in titles)
        metadata += "".join(f"<dc:creator>{escape(c)}</dc:creator>" for c in creators)
        parts = [
            (
                name,
                body.replace(b"<dc:title>A synthetic volume</dc:title>", metadata.encode())
                if name == "EPUB/book.opf"
                else body,
            )
            for name, body in fixture_parts()
        ]
        job = complete(enqueue(archive(parts)))
        params = {
            **pin(client),
            "work": "w_fixture",
            "source_sha256": job.target_id,
            "report_sha256": job.result["report_sha256"],
            **query,
        }
        result = client.get(f"/api/epub-inspections/{job.pk}/comparison", params)
        return result, job, params

    return run, path


def test_comparison_inspection_survives_background_lease_renewal(comparison, monkeypatch):
    run, _ = comparison
    heartbeat = threading.Event()
    renewals = []
    original_renew = file_inspections.renew
    original_inspect = file_inspections.inspect_isolated

    def observe_renewal(*args):
        renewed = original_renew(*args)
        if threading.current_thread().name == f"epub-lease-{args[0]}":
            renewals.append((threading.current_thread(), renewed))
            heartbeat.set()
        return renewed

    def inspect_after_heartbeat(*args):
        assert heartbeat.wait(timeout=5)
        return original_inspect(*args)

    monkeypatch.setattr(file_inspections, "HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(file_inspections, "renew", observe_renewal)
    monkeypatch.setattr(file_inspections, "inspect_isolated", inspect_after_heartbeat)

    response, job, _ = run()

    assert renewals and all(renewed for _, renewed in renewals)
    assert all(not thread.is_alive() for thread, _ in renewals)
    assert job.state == "succeeded"
    assert response.status_code == 200


def test_alias_comparison_preserves_names_and_binds_every_source(client, comparison):
    run, path = comparison
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    response, job, params = run()
    assert response.status_code == 200
    data = response.json()
    assert data["schema_version"] == "librarium.package-comparison.v3"
    assert data["policy_version"] == "librarium.package-metadata.v3"
    assert data["job_id"] == str(job.pk)
    assert data["source_sha256"] == params["source_sha256"]
    assert data["report_sha256"] == params["report_sha256"]
    assert data["catalogue"] == {
        "work_id": "w_fixture",
        "title": "A synthetic volume",
        "authors": [{"id": "1", "name": "Josh Reynolds"}],
        "version": params["version"],
        "sha256": params["sha256"],
        "fixture": True,
    }
    assert data["title"]["status"] == "same"
    assert data["creators"]["status"] == "same"
    assert data["creators"]["epub"] == ["Joshua Reynolds"]
    assert data["creators"]["matches"] == [
        {
            "epub_name": "Joshua Reynolds",
            "author_id": "1",
            "catalogue_name": "Josh Reynolds",
            "basis": "alias",
            "status": "same",
        }
    ]
    assert data["metadata_agrees"] is True and data["ready"] is False
    assert "roles" in data["scope"] and "identify" in data["scope"]
    assert data["inspection_complete"] is True
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    original = deepcopy(job.result)
    assert client.get(f"/api/epub-inspections/{job.pk}/comparison", params).json() == data
    job.refresh_from_db()
    assert job.result == original and Job.objects.count() == 1
    assert "Joshua Reynolds" not in json.dumps(job.input)


def test_actual_preserved_report_supplies_bound_isbn_evidence(client, comparison):
    _, path = comparison
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE edition SET isbn13='9780306406157'")
    parts = []
    for name, body in fixture_parts():
        if name == "EPUB/book.opf":
            body = body.replace(
                b"</metadata>",
                b"<dc:identifier>urn:isbn:0-306-40615-2</dc:identifier></metadata>",
            )
        parts.append((name, body))
    data = archive(parts)
    job = complete(enqueue(data))
    original_result = deepcopy(job.result)
    params = {
        **pin(client),
        "work": "w_fixture",
        "source_sha256": job.target_id,
        "report_sha256": job.result["report_sha256"],
    }
    result = client.get(f"/api/epub-inspections/{job.pk}/comparison", params)
    assert result.status_code == 200
    assert result.json()["isbn"]["status"] == "same"
    assert result.json()["isbn"]["entries"][-1]["source"] == "urn:isbn:0-306-40615-2"
    assert job.input["source_version"] == "librarium.epub-structure.v11"
    assert artifacts.read("source", job.target_id, len(data)) == data
    job.refresh_from_db()
    assert job.result == original_result


@pytest.mark.parametrize(
    "kind,state,basis",
    [
        ("epub2", "same", "opf_scheme"),
        ("epub3", "same", "onix_isbn13"),
        ("alias", "same", "onix_isbn13"),
        ("remapped", "unknown", None),
        ("duplicate_id", "ambiguous", None),
        ("markup", "unknown", None),
    ],
)
def test_native_report_declarations_drive_the_bound_api_comparison(
    client, comparison, kind, state, basis
):
    parts = []
    for name, body in fixture_parts():
        if name == "EPUB/book.opf":
            declaration = b'<dc:identifier id="isbn">9780306406157</dc:identifier>'
            if kind == "epub2":
                body = body.replace(b'version="3.0"', b'version="2.0"')
                declaration = b'<dc:identifier xmlns:old="http://www.idpf.org/2007/opf" old:scheme="ISBN" id="isbn">9780306406157</dc:identifier>'
            else:
                if kind == "alias":
                    body = body.replace(
                        b'unique-identifier="uid"',
                        b'unique-identifier="uid" prefix="types: http://www.editeur.org/ONIX/book/codelists/current.html#"',
                    )
                if kind == "remapped":
                    body = body.replace(
                        b'unique-identifier="uid"',
                        b'unique-identifier="uid" prefix="onix: https://example.invalid/types#"',
                    )
                scheme = b"types:codelist5" if kind == "alias" else b"onix:codelist5"
                declaration += (
                    b'<meta refines="#isbn" property="identifier-type" scheme="'
                    + scheme
                    + b'">15</meta>'
                )
            if kind == "duplicate_id":
                body = body.replace(b"<manifest>", b'<manifest><extension id="isbn"/>')
            if kind == "markup":
                declaration = declaration.replace(
                    b">9780306406157<", b">978<foreign>0306406157</foreign><"
                )
            body = body.replace(b"</metadata>", declaration + b"</metadata>")
        parts.append((name, body))
    data = archive(parts)
    job = complete(enqueue(data))
    before = deepcopy(job.result)
    source = file_inspections.report(job)["report"]
    params = {
        **pin(client),
        "work": "w_fixture",
        "source_sha256": job.target_id,
        "report_sha256": job.result["report_sha256"],
    }
    response = client.get(f"/api/epub-inspections/{job.pk}/comparison", params)
    assert response.status_code == 200, response.json()
    result = response.json()
    assert result["schema_version"] == "librarium.package-comparison.v3"
    assert result["isbn"]["capture"] == "recorded"
    assert result["isbn"]["status"] == state
    assert result["isbn"]["entries"][-1]["basis"] == basis
    assert (
        result["isbn"]["entries"][-1]["source_position"]["document_sha256"]
        == source["package"]["byte_sha256"]
    )
    assert artifacts.read("source", job.target_id, len(data)) == data
    job.refresh_from_db()
    assert job.result == before


@pytest.mark.parametrize(
    "creators,titles,title_state,creator_state",
    [
        (("Josh Reynolds",), ("  A   SYNTHETIC volume ",), "same", "same"),
        (("Josh Reynolds",), ("A synthetic volume: a subtitle",), "different", "same"),
        (("Josh Reynolds",), ("The synthetic volume",), "different", "same"),
        (("Chris Reynolds",), ("A synthetic volume",), "same", "different"),
        (("Reynolds",), ("A synthetic volume",), "same", "different"),
        (("Josh Reynolds", "Other Author"), ("A synthetic volume",), "same", "partial"),
        (("Josh Reynolds", "Joshua Reynolds"), ("A synthetic volume",), "same", "ambiguous"),
        ((), ("A synthetic volume",), "same", "unknown"),
        (("",), ("A synthetic volume",), "same", "unknown"),
        (("Various Authors",), ("A synthetic volume",), "same", "unknown"),
        (("Josh Reynolds",), (), "unknown", "same"),
        (("Josh Reynolds",), ("A synthetic volume", "Other title"), "ambiguous", "same"),
    ],
)
def test_conservative_comparison_requires_complete_unambiguous_names(
    comparison, creators, titles, title_state, creator_state
):
    run, _ = comparison
    response, _, _ = run(creators, titles)
    assert response.status_code == 200
    data = response.json()
    assert data["title"]["status"] == title_state
    assert data["creators"]["status"] == creator_state
    assert data["metadata_agrees"] is (title_state == creator_state == "same")


def test_missing_coauthor_and_editor_are_not_complete_author_agreement(comparison):
    run, path = comparison
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO author VALUES (2,'Second Author',NULL)")
        db.execute("INSERT INTO work_author VALUES ('w_fixture',2,'author')")
        db.execute("INSERT INTO author VALUES (3,'An Editor',NULL)")
        db.execute("INSERT INTO work_author VALUES ('w_fixture',3,'editor')")
    response, _, _ = run()
    assert response.status_code == 200
    data = response.json()
    assert data["creators"]["status"] == "partial"
    assert data["creators"]["missing_authors"] == [{"id": "2", "name": "Second Author"}]
    assert all(a["id"] != "3" for a in data["catalogue"]["authors"])


def test_complete_coauthors_can_be_reordered_and_ids_remain_exact_strings(comparison):
    run, path = comparison
    identity = 2**63 - 1
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO author VALUES (?,'Second Author',NULL)", (identity,))
        db.execute("INSERT INTO work_author VALUES ('w_fixture',?,'author')", (identity,))
    response, _, _ = run(("Second Author", "Joshua Reynolds"))
    assert response.status_code == 200
    data = response.json()
    assert data["metadata_agrees"] is True
    assert data["creators"]["matches"][0]["author_id"] == str(identity)
    assert data["creators"]["missing_authors"] == []


def test_missing_author_credits_are_unknown(comparison):
    run, path = comparison
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DELETE FROM work_author")
    response, _, _ = run()
    assert response.status_code == 200
    assert response.json()["creators"]["status"] == "unknown"
    assert response.json()["metadata_agrees"] is False


@pytest.mark.parametrize("collision", ["alias", "canonical"])
def test_global_normalized_collision_cannot_confirm_a_selected_author(comparison, collision):
    run, path = comparison
    with closing(sqlite3.connect(path)) as db, db:
        name = " JOSHUA  REYNOLDS " if collision == "canonical" else "Other Author"
        db.execute("INSERT INTO author VALUES (2,?,NULL)", (name,))
        if collision == "alias":
            db.execute("INSERT INTO author_alias VALUES (2,' JOSHUA  REYNOLDS ')")
    response, _, _ = run()
    assert response.status_code == 200
    data = response.json()
    assert data["creators"]["status"] == "ambiguous"
    assert data["creators"]["matches"][0]["author_id"] is None
    assert data["metadata_agrees"] is False


@pytest.mark.parametrize("collision", ["alias", "canonical"])
def test_global_name_budget_cannot_hide_a_normalized_collision(comparison, collision):
    run, path = comparison
    spelling = " " * 513 + "Joshua Reynolds"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "INSERT INTO author VALUES (2,?,NULL)",
            (spelling if collision == "canonical" else "Other Author",),
        )
        if collision == "alias":
            db.execute("INSERT INTO author_alias VALUES (2,?)", (spelling,))
    response, _, _ = run()
    assert response.status_code == 422
    assert "metadata_agrees" not in response.json()


def test_unicode_normalization_keeps_punctuation_and_does_not_expand_nicknames(comparison):
    run, path = comparison
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE author SET name='Émilie O’Connor' WHERE id=1")
    response, _, _ = run(("E\u0301milie O’Connor",))
    assert response.status_code == 200
    assert response.json()["creators"]["status"] == "same"
    response, _, _ = run(("Émilie OConnor",))
    assert response.json()["creators"]["status"] == "different"


def test_incomplete_report_does_not_promote_partial_metadata(client, comparison):
    run, _ = comparison
    _, job, params = run()
    report = file_inspections.report(job)["report"]
    report["inspection_complete"] = False
    from librarium.content_evidence import unconfirmed, unconfirmed_document_text

    report["content_evidence"] = unconfirmed(report["source_sha256"], "inspection_incomplete")
    report["document_text_evidence"] = unconfirmed_document_text(
        report["source_sha256"], "inspection_incomplete"
    )
    stored = artifacts.write_report(report)
    job.result.update(
        report_sha256=stored["sha256"], report_size=stored["size"], inspection_complete=False
    )
    job.save()
    params["report_sha256"] = stored["sha256"]
    response = client.get(f"/api/epub-inspections/{job.pk}/comparison", params)
    assert response.status_code == 200
    data = response.json()
    assert data["inspection_complete"] is False
    assert data["title"]["status"] == data["creators"]["status"] == "unknown"
    assert data["metadata_agrees"] is False


@pytest.mark.parametrize("field", ["source_sha256", "report_sha256", "sha256", "version", "work"])
def test_each_identity_pin_is_required_and_refuses_substitution(client, comparison, field):
    run, _ = comparison
    _, job, params = run()
    url = f"/api/epub-inspections/{job.pk}/comparison"
    missing = {key: value for key, value in params.items() if key != field}
    assert client.get(url, missing).status_code == 400
    replacement = (
        "2026.10.25.2" if field == "version" else "w_other" if field == "work" else "f" * 64
    )
    assert client.get(url, {**params, field: replacement}).status_code in {404, 409}
    assert client.get(url, {**params, field: [params[field], params[field]]}).status_code == 400


def test_only_get_and_supported_fields_are_accepted(client, comparison):
    run, _ = comparison
    _, job, params = run()
    url = f"/api/epub-inspections/{job.pk}/comparison"
    assert client.post(url, params).status_code == 405
    assert client.get(url, {**params, "title": "forged title"}).status_code == 400
    job.state = "queued"
    job.save()
    assert client.get(url, params).status_code == 409


@pytest.mark.parametrize(
    "query",
    [
        {"version": "2026.99.99.1"},
        {"sha256": "invalid"},
        {"source_sha256": "../file"},
        {"work": "w\nforged"},
        {"work": "x" * 81},
    ],
)
def test_malformed_pins_are_refused_before_comparison(comparison, query):
    run, _ = comparison
    response, _, _ = run(**query)
    assert response.status_code == 400


def test_report_and_source_integrity_are_rechecked(client, comparison, artifact_store):
    run, _ = comparison
    _, job, params = run()
    source = artifact_store / f"source-{job.target_id}"
    source.chmod(0o600)
    data = source.read_bytes()
    source.write_bytes(b"x" + data[1:])
    response = client.get(f"/api/epub-inspections/{job.pk}/comparison", params)
    assert response.status_code == 503


def test_alias_schema_and_comparison_budgets_refuse_without_a_positive_claim(comparison):
    run, path = comparison
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DROP TABLE author_alias")
    response, _, _ = run()
    assert response.status_code == 503
    assert "metadata_agrees" not in response.json()


def test_author_count_is_bounded_without_silent_truncation(comparison):
    run, path = comparison
    with closing(sqlite3.connect(path)) as db, db:
        for index in range(2, 67):
            db.execute("INSERT INTO author VALUES (?,?,NULL)", (index, f"Author {index}"))
            db.execute("INSERT INTO work_author VALUES ('w_fixture',?,'author')", (index,))
    response, _, _ = run()
    assert response.status_code == 422


def test_package_names_are_bounded_without_silent_truncation(comparison):
    run, _ = comparison
    response, _, _ = run(tuple(f"Creator {i}" for i in range(65)))
    assert response.status_code == 422
