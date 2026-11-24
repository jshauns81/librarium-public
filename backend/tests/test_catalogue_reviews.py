import json
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from librarium.catalogue import CatalogueError
from librarium.catalogue_reviews import INPUT_LIMIT, SCOPE, capture_catalogue
from librarium.models import Job, Work
from librarium.seed import seed
from librarium.services import advance, cancel, claim, enqueue, enqueue_catalogue

VERSION = "2026.10.25.1"
SCHEMA = Path(__file__).parent / "fixtures/blc-schema.sql"
WORK = "w_review"


def build(root: Path, version: str = VERSION, editions=None, support=None, synopsis="Prose"):
    """Write a pinned snapshot with one reviewable work and return its fingerprint pin."""
    root.mkdir(exist_ok=True)
    path = root / f"{version}.sqlite"
    path.unlink(missing_ok=True)
    if editions is None:
        editions = [
            ("e1", "hardback", "0306406152", "9780306406157", "Fixture Press", "2001-01-01"),
            ("e2", "ebook", None, "9780306406158", "Fixture Press", None),
            ("e3", "paperback", "0306406153", None, None, "2002-02-02"),
            ("e4", "paperback", "0141036141", "9780306406157", "Fixture Press", "2003"),
            ("e5", "audiobook", None, None, "Fixture Audio", "2004"),
            ("e6", "ebook", "080442957X", "9791090636071", "Fixture Press", "2005"),
        ]
    if support is None:
        support = [
            ("title", "Fixture: The Review", ["lexicanum", "openlibrary"], []),
            (
                "first_published",
                "2001",
                ["lexicanum"],
                [{"origin": "goodreads", "value": "2000"}],
            ),
        ]
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(SCHEMA.read_text())
        db.execute("INSERT INTO meta VALUES ('catalog_version', ?)", (version,))
        db.execute(
            "INSERT INTO work(id, title, synopsis, type, first_published) "
            "VALUES (?, 'Fixture: The Review', ?, 'novel', NULL)",
            (WORK, synopsis),
        )
        db.execute("INSERT INTO author VALUES (1, 'Fixture Author', 'Author')")
        db.execute("INSERT INTO work_author VALUES (?, 1, 'author')", (WORK,))
        db.executemany(
            "INSERT INTO edition(id, work_id, format, isbn10, isbn13, publisher, release_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(e[0], WORK, *e[1:]) for e in editions],
        )
        db.executemany(
            "INSERT INTO field_support VALUES ('work', ?, ?, ?, 0.5, ?, ?)",
            [(WORK, f, v, json.dumps(a), json.dumps(d)) for f, v, a, d in support],
        )
    (root / "current").write_text(version)
    import hashlib

    return {
        "catalogue_work_id": WORK,
        "version": version,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


@pytest.fixture
def snapshot(tmp_path, settings):
    root = tmp_path / "catalogue"
    settings.LIBRARIUM_CATALOGUE_DIR = str(root)
    settings.LIBRARIUM_CATALOGUE_FIXTURE = False
    return root


def run(job_id=None):
    item = claim()
    assert item is not None
    if job_id is not None:
        assert item.pk == job_id
    for _ in range(item.checkpoint, 4):
        assert advance(item.pk, item.lease_token)
    return Job.objects.get(pk=item.pk)


def keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from keys(item)


def finding(job, name):
    return next(f for f in job.result["findings"] if f["name"] == name)


def test_capture_is_compact_pinned_and_free_of_library_or_file_claims(db, snapshot):
    pin = build(snapshot)
    captured = capture_catalogue(WORK, pin["version"], pin["sha256"])
    assert captured["kind"] == "catalogue"
    assert captured["catalogue_work_id"] == WORK
    assert captured["title"] == "Fixture: The Review"
    assert captured["source_version"] == VERSION
    assert captured["source_sha256"] == pin["sha256"]
    assert captured["fixture"] is False
    assert captured["has_synopsis"] is True
    assert "synopsis" not in captured
    assert captured["edition_count"] == 6
    assert captured["editions_truncated"] is False
    assert captured["support_count"] == 2
    assert captured["support_truncated"] is False
    text = json.dumps(captured)
    assert "Prose" not in text
    assert not {k for k in keys(captured) if "library" in k or "file" in k or "uuid" in k}
    assert len(json.dumps(captured, separators=(",", ":")).encode()) <= INPUT_LIMIT


@pytest.mark.parametrize(
    "work, version, sha, status",
    [
        ("missing", VERSION, None, 404),
        (WORK, VERSION, "0" * 64, 409),
        (WORK, "2026.10.25.9", None, 409),
        (WORK, "", "", 400),
        (WORK, "not-a-version", None, 400),
    ],
)
def test_capture_requires_a_known_work_and_an_exact_pin(db, snapshot, work, version, sha, status):
    pin = build(snapshot)
    with pytest.raises(CatalogueError) as error:
        capture_catalogue(work, version, pin["sha256"] if sha is None else sha)
    assert error.value.status == status


def test_unconfigured_catalogue_cannot_be_captured(db, settings):
    settings.LIBRARIUM_CATALOGUE_DIR = ""
    with pytest.raises(CatalogueError):
        capture_catalogue(WORK, VERSION, "a" * 64)


def test_oversized_metadata_is_rejected_rather_than_trimmed(db, snapshot):
    editions = [(f"e{i:03}", "ebook", None, None, "P" * 400, "2001") for i in range(200)]
    pin = build(snapshot, editions=editions)
    with pytest.raises(CatalogueError) as error:
        capture_catalogue(WORK, pin["version"], pin["sha256"])
    assert error.value.status == 422
    assert "64 KiB" in str(error.value)
    with pytest.raises(CatalogueError):
        enqueue_catalogue(pin, str(uuid.uuid4()))
    assert Job.objects.count() == 0


def test_real_review_reports_checksums_consistency_duplicates_and_sources(db, snapshot):
    pin = build(snapshot)
    job = enqueue_catalogue(pin, str(uuid.uuid4()))
    assert job.kind == "catalogue"
    assert job.target_id == WORK
    assert job.work_id is None
    assert job.fixture_failure is False
    done = run(job.pk)
    assert done.state == "succeeded"
    assert done.checkpoint == 4
    result = done.result
    assert result["read_only"] is True
    assert result["synthetic"] is False
    assert result["kind"] == "catalogue"
    assert result["input_fingerprint"] == done.input_fingerprint
    assert result["source_version"] == VERSION
    assert result["source_sha256"] == pin["sha256"]
    assert result["catalogue_work_id"] == WORK
    assert result["scope"] == SCOPE
    assert "score" not in json.dumps(result)
    assert not {k for k in keys(result) if "library" in k or "file" in k}
    for item in result["findings"]:
        assert {"name", "ok", "detail"} <= set(item)
        assert isinstance(item["ok"], bool)

    isbn = finding(done, "ISBN checks")
    counts = isbn["counts"]
    assert counts["isbn13_invalid"] == 1
    assert counts["isbn10_invalid"] == 1
    assert counts["pairs_mismatched"] == 2  # e4 points at another book; e6 is a 979 ISBN
    assert counts["no_isbn"] == 1
    assert counts["duplicate_isbn13"] == 1
    assert isbn["ok"] is False
    problems = {(p["edition_id"], p["problem"]) for p in isbn["items"]}
    assert ("e2", "isbn13_checksum") in problems
    assert ("e3", "isbn10_checksum") in problems
    assert ("e4", "isbn_pair_mismatch") in problems
    assert ("e6", "isbn_pair_mismatch") in problems
    assert ("e1", "duplicate_isbn13") in problems
    assert not any(p[0] == "e5" for p in problems)  # absence is not invalidity
    assert "9780306406158" in isbn["detail"] or any(
        p.get("value") == "9780306406158" for p in isbn["items"]
    )

    sources = finding(done, "Source agreement")
    assert sources["ok"] is False
    assert sources["counts"]["disagreements"] == 1
    entry = sources["items"][0]
    assert entry["field"] == "first_published"
    assert entry["agree"] == ["lexicanum"]
    assert entry["disagree"] == [{"origin": "goodreads", "value": "2000", "value_truncated": False}]

    bibliography = finding(done, "Bibliography completeness")
    assert "first_published" in bibliography["missing"]
    assert bibliography["counts"]["editions_missing_publisher"] == 1
    assert bibliography["counts"]["editions_missing_release_date"] == 1
    assert bibliography["ok"] is False
    assert result["coverage"]["complete"] is True
    assert Work.objects.count() == 0


def test_clean_work_passes_without_claiming_more_than_it_checked(db, snapshot):
    pin = build(
        snapshot,
        editions=[("e1", "hardback", "0306406152", "9780306406157", "Fixture Press", "2001")],
        support=[("title", "Fixture: The Review", ["lexicanum"], [])],
    )
    with patch("librarium.catalogue_reviews.bibliography_finding") as bib:
        bib.return_value = {"name": "Bibliography completeness", "ok": True, "detail": "x"}
        done = run(enqueue_catalogue(pin, str(uuid.uuid4())).pk)
    assert finding(done, "ISBN checks")["ok"] is True
    assert finding(done, "Source agreement")["ok"] is True


def test_missing_isbns_and_support_are_reported_as_unchecked_not_wrong(db, snapshot):
    pin = build(
        snapshot,
        editions=[("e1", "audiobook", None, "", "Audio", "2001")],
        support=[],
        synopsis=None,
    )
    done = run(enqueue_catalogue(pin, str(uuid.uuid4())).pk)
    isbn = finding(done, "ISBN checks")
    assert isbn["status"] == "not_checked"
    assert isbn["counts"]["isbn13_invalid"] == 0 and isbn["counts"]["no_isbn"] == 1
    assert "invalid" not in isbn["detail"].lower()
    assert finding(done, "Source agreement")["status"] == "not_checked"
    assert "synopsis" in finding(done, "Bibliography completeness")["missing"]


def test_truncated_inputs_are_disclosed_and_never_pass(db, snapshot):
    editions = [
        (f"e{i:03}", "ebook", None, "9780306406157" if i == 0 else None, "P", "2001")
        for i in range(205)
    ]
    support = [(f"f{i:03}", "v", ["a"], []) for i in range(105)]
    pin = build(snapshot, editions=editions, support=support)
    captured = capture_catalogue(WORK, pin["version"], pin["sha256"])
    assert captured["edition_count"] == 205 and len(captured["editions"]) == 200
    assert captured["editions_truncated"] is True
    assert captured["support_count"] == 105 and len(captured["support"]) == 100
    assert captured["support_truncated"] is True
    done = run(enqueue_catalogue(pin, str(uuid.uuid4())).pk)
    assert done.result["coverage"]["complete"] is False
    isbn = finding(done, "ISBN checks")
    assert isbn["ok"] is False and isbn["status"] == "partial"
    assert "200 of 205" in isbn["detail"]
    sources = finding(done, "Source agreement")
    assert sources["ok"] is False and sources["status"] == "partial"
    assert "100 of 105" in sources["detail"]


def test_fixture_snapshot_is_labelled_synthetic(db, snapshot, settings):
    settings.LIBRARIUM_CATALOGUE_FIXTURE = True
    pin = build(snapshot)
    done = run(enqueue_catalogue(pin, str(uuid.uuid4())).pk)
    assert done.input["fixture"] is True
    assert done.result["synthetic"] is True


def test_long_values_are_bounded_in_findings(db, snapshot):
    long = "x" * 2000
    pin = build(snapshot, support=[("title", "t", ["a"], [{"origin": "b", "value": long}])])
    done = run(enqueue_catalogue(pin, str(uuid.uuid4())).pk)
    text = json.dumps(done.result)
    assert long not in text
    assert len(finding(done, "Source agreement")["items"][0]["disagree"][0]["value"]) <= 160


def test_capture_keeps_long_source_text_out_of_the_input_as_marked_excerpts(db, snapshot):
    prose, other = "Prose " * 500, "Other prose " * 500
    origins = [f"origin{i:02}" for i in range(30)]
    support = [
        ("synopsis", prose, ["lexicanum"], [{"origin": o, "value": other} for o in origins]),
        ("title", "Fixture: The Review", ["lexicanum", "openlibrary"], []),
    ]
    pin = build(snapshot, support=support, synopsis=prose)
    captured = capture_catalogue(WORK, pin["version"], pin["sha256"])
    text = json.dumps(captured)
    assert prose[:400] not in text and other[:400] not in text
    synopsis, title = captured["support"]
    assert synopsis["field"] == "synopsis"
    assert "value" not in synopsis  # a cut value is never stored as the value
    assert len(synopsis["excerpt"]) <= 160 and synopsis["excerpt"].endswith("…")
    assert prose.startswith(synopsis["excerpt"][:-1])
    assert [d["origin"] for d in synopsis["disagree"]] == origins  # no conflict is dropped
    assert all("value" not in d and len(d["excerpt"]) <= 160 for d in synopsis["disagree"])
    assert title == {
        "field": "title",
        "value": "Fixture: The Review",
        "agree": ["lexicanum", "openlibrary"],
        "disagree": [],
    }
    assert captured["support_count"] == 2 and captured["support_truncated"] is False

    job = enqueue_catalogue(pin, str(uuid.uuid4()))
    assert job.input == captured
    done = run(job.pk)
    result = json.dumps(done.result)
    assert prose[:400] not in result and other[:400] not in result
    sources = finding(done, "Source agreement")
    assert sources["counts"]["disagreements"] == 1
    assert sources["counts"]["origins"] == 32  # lexicanum, openlibrary and 30 dissenters
    assert sources["counts"]["excerpted"] == 1
    assert "excerpt" in sources["detail"] and "160" in sources["detail"]
    item = sources["items"][0]
    assert item["value_truncated"] is True
    assert item["disagree_count"] == 30 and len(item["disagree"]) == 25
    assert item["agree_count"] == 1
    assert "25 of 30" in sources["detail"]
    assert all(d["value_truncated"] for d in item["disagree"])


def test_list_values_stay_lists_and_are_cut_by_length(db, snapshot):
    names = [f"Author Number {i:03}" for i in range(40)]
    support = [
        (
            "author",
            "Fixture Author",
            ["lexicanum"],
            [
                {"origin": "goodreads", "value": names},
                {"origin": "openlibrary", "value": ["Fixture Author", "Other"]},
            ],
        )
    ]
    pin = build(snapshot, support=support)
    captured = capture_catalogue(WORK, pin["version"], pin["sha256"])
    long, short = captured["support"][0]["disagree"]
    assert short == {"origin": "openlibrary", "value": ["Fixture Author", "Other"]}
    assert "value" not in long and isinstance(long["excerpt"], list)
    assert long["excerpt"][:-1] == names[: len(long["excerpt"]) - 1]
    assert len(json.dumps(long["excerpt"], ensure_ascii=False, separators=(",", ":"))) <= 160
    assert long["excerpt"][-1].endswith("…")
    item = finding(run(enqueue_catalogue(pin, str(uuid.uuid4())).pk), "Source agreement")["items"][
        0
    ]
    shown = {d["origin"]: d for d in item["disagree"]}
    assert shown["goodreads"]["value_truncated"] is True
    assert shown["openlibrary"] == {
        "origin": "openlibrary",
        "value": '["Fixture Author","Other"]',
        "value_truncated": False,
    }
    assert shown["goodreads"]["value"] == json.dumps(
        long["excerpt"], ensure_ascii=False, separators=(",", ":")
    )  # displayed whole, not cut a second time


def test_inputs_captured_before_excerpts_still_review_and_disclose_cuts(db, snapshot):
    from librarium.catalogue_reviews import source_finding

    pin = build(snapshot)
    payload = capture_catalogue(WORK, pin["version"], pin["sha256"])
    payload["support"] = [
        {
            "field": "synopsis",
            "value": "Old " * 100,
            "agree": ["a"],
            "disagree": [{"origin": "b", "value": "Older " * 100}],
        }
    ]
    sources = source_finding(payload)
    assert sources["counts"]["excerpted"] == 1
    assert sources["items"][0]["value_truncated"] is True
    assert sources["items"][0]["disagree"][0]["value_truncated"] is True
    assert "Old " * 100 not in json.dumps(sources)


def test_short_conflicts_are_not_called_excerpts(db, snapshot):
    pin = build(snapshot)
    done = run(enqueue_catalogue(pin, str(uuid.uuid4())).pk)
    sources = finding(done, "Source agreement")
    assert sources["counts"]["excerpted"] == 0
    assert "excerpt" not in sources["detail"]
    item = sources["items"][0]
    assert item["value_truncated"] is False
    assert item["disagree"] == [{"origin": "goodreads", "value": "2000", "value_truncated": False}]


def test_long_duplicate_isbns_are_bounded(db, snapshot):
    long = "9" * 300
    pin = build(
        snapshot,
        editions=[
            ("e1", "ebook", None, long, "P", "2001"),
            ("e2", "ebook", None, long, "P", "2001"),
        ],
    )
    done = run(enqueue_catalogue(pin, str(uuid.uuid4())).pk)
    isbn = finding(done, "ISBN checks")
    assert isbn["counts"]["duplicate_isbn13"] == 1
    duplicates = [i for i in isbn["items"] if i["problem"] == "duplicate_isbn13"]
    assert {i["edition_id"] for i in duplicates} == {"e1", "e2"}
    assert all(len(i["value"]) <= 160 for i in isbn["items"])
    assert long not in json.dumps(done.result)


def test_input_is_immutable_and_worker_needs_no_catalogue_mount(db, snapshot, settings):
    pin = build(snapshot)
    key = str(uuid.uuid4())
    job = enqueue_catalogue(pin, key)
    frozen = (job.input, job.input_fingerprint)
    build(snapshot, editions=[], support=[])  # same filename, different bytes
    settings.LIBRARIUM_CATALOGUE_DIR = ""
    assert enqueue_catalogue(pin, key).pk == job.pk  # replay does not reread the snapshot
    done = run(job.pk)
    assert done.state == "succeeded"
    assert (done.input, done.input_fingerprint) == frozen
    assert finding(done, "ISBN checks")["counts"]["isbn13_invalid"] == 1


def test_request_key_replay_and_conflicts_are_global(db, snapshot):
    seed(2)
    pin = build(snapshot)
    key = str(uuid.uuid4())
    job = enqueue_catalogue(pin, key)
    assert enqueue_catalogue(dict(pin), key).pk == job.pk
    with pytest.raises(CatalogueError) as error:
        enqueue_catalogue({**pin, "sha256": "b" * 64}, key)
    assert error.value.status == 409
    with pytest.raises(ValueError, match="different"):
        enqueue("demo-00001", key)
    synthetic = enqueue("demo-00002", str(uuid.uuid4()))
    with pytest.raises(CatalogueError) as error:
        enqueue_catalogue(pin, str(synthetic.request_key))
    assert error.value.status == 409


def test_one_active_review_per_catalogue_work_even_across_pins(db, snapshot):
    pin = build(snapshot)
    other = build(snapshot, version="2026.10.25.2")
    job = enqueue_catalogue(pin, str(uuid.uuid4()))
    for candidate in (pin, other):
        with pytest.raises(CatalogueError) as error:
            enqueue_catalogue(candidate, str(uuid.uuid4()))
        assert error.value.status == 409
    cancel(job.pk)
    again = enqueue_catalogue(other, str(uuid.uuid4()))
    assert again.input["source_version"] == "2026.10.25.2"
    assert Job.objects.filter(kind="catalogue", target_id=WORK).count() == 2


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"catalogue_work_id": WORK, "version": VERSION},
        {"catalogue_work_id": WORK, "version": VERSION, "sha256": "a" * 64, "x": 1},
        {"catalogue_work_id": "", "version": VERSION, "sha256": "a" * 64},
        {"catalogue_work_id": "x" * 81, "version": VERSION, "sha256": "a" * 64},
        {"catalogue_work_id": "a\x00", "version": VERSION, "sha256": "a" * 64},
        {"catalogue_work_id": 5, "version": VERSION, "sha256": "a" * 64},
        {"catalogue_work_id": WORK, "version": VERSION, "sha256": "A" * 64},
    ],
)
def test_invalid_payloads_are_bad_requests(db, snapshot, payload):
    with pytest.raises(CatalogueError) as error:
        enqueue_catalogue(payload, str(uuid.uuid4()))
    assert error.value.status == 400


def test_invalid_request_key_is_a_bad_request(db, snapshot):
    pin = build(snapshot)
    with pytest.raises(CatalogueError) as error:
        enqueue_catalogue(pin, "not-a-uuid")
    assert error.value.status == 400


def test_database_rejects_a_second_active_review_and_malformed_rows(db, snapshot):
    pin = build(snapshot)
    job = enqueue_catalogue(pin, str(uuid.uuid4()))
    base = {"input": job.input, "input_fingerprint": job.input_fingerprint}
    with pytest.raises(IntegrityError), transaction.atomic():
        Job.objects.create(kind="catalogue", target_id=WORK, request_key=uuid.uuid4(), **base)
    with pytest.raises(IntegrityError), transaction.atomic():
        Job.objects.create(
            kind="catalogue",
            target_id="w_other",
            request_key=uuid.uuid4(),
            fixture_failure=True,
            **base,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        Job.objects.create(kind="catalogue", target_id="", request_key=uuid.uuid4(), **base)
    with pytest.raises(IntegrityError), transaction.atomic():
        Job.objects.create(kind="synthetic", request_key=uuid.uuid4(), **base)


def test_legacy_synthetic_job_rows_may_leave_target_blank(db):
    seed(1)
    legacy = Job.objects.create(
        work_id="demo-00001", request_key=uuid.uuid4(), input={}, input_fingerprint="x"
    )
    assert legacy.kind == "synthetic" and legacy.target_id == ""
    with pytest.raises(ValueError, match="active"):
        enqueue("demo-00001", str(uuid.uuid4()))  # the per-Work guard still applies


def test_synthetic_enqueue_records_its_target(db):
    seed(1)
    job = enqueue("demo-00001", str(uuid.uuid4()))
    assert job.kind == "synthetic"
    assert job.target_id == "demo-00001"


def test_lease_fencing_recovery_and_durable_findings(db, snapshot):
    pin = build(snapshot)
    job = enqueue_catalogue(pin, str(uuid.uuid4()))
    old = claim()
    assert old.message == "Reviewing catalogue metadata"
    assert advance(old.pk, old.lease_token)
    assert advance(old.pk, old.lease_token)
    first = Job.objects.get(pk=job.pk).result["findings"][0]
    Job.objects.filter(pk=job.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    recovered = claim()
    assert recovered.pk == job.pk and recovered.checkpoint == 2
    assert recovered.message == "Resuming from saved progress"
    assert not advance(old.pk, old.lease_token)
    with patch(
        "librarium.catalogue_reviews.source_finding", side_effect=AssertionError("recomputed")
    ):
        assert advance(recovered.pk, recovered.lease_token)
        assert advance(recovered.pk, recovered.lease_token)
    done = Job.objects.get(pk=job.pk)
    assert done.state == "succeeded"
    assert done.result["findings"][0] == first
    assert [f["name"] for f in done.result["findings"]] == [
        "Source agreement",
        "ISBN checks",
        "Bibliography completeness",
    ]
    assert done.attempts == 2
    assert not advance(recovered.pk, recovered.lease_token)


def test_cancel_fences_a_running_review(db, snapshot):
    pin = build(snapshot)
    job = enqueue_catalogue(pin, str(uuid.uuid4()))
    item = claim()
    assert advance(item.pk, item.lease_token)
    cancel(job.pk)
    assert not advance(item.pk, item.lease_token)
    job.refresh_from_db()
    assert job.state == "cancelled"
    assert claim() is None


def test_real_review_never_uses_fixture_failure(db, snapshot):
    pin = build(snapshot)
    job = enqueue_catalogue(pin, str(uuid.uuid4()))
    assert job.fixture_failure is False
    done = run(job.pk)
    assert "fixture" not in done.message.lower()


@pytest.mark.django_db(transaction=True)
def test_worker_runs_real_reviews_without_artificial_delay(tmp_path, settings):
    root = tmp_path / "catalogue"
    settings.LIBRARIUM_CATALOGUE_DIR = str(root)
    settings.LIBRARIUM_CATALOGUE_FIXTURE = False
    job = enqueue_catalogue(build(root), str(uuid.uuid4()))
    with patch("librarium.management.commands.inspection_worker.time.sleep") as sleep:
        call_command("inspection_worker", once=True, step_seconds=2)
    assert all(call.args[0] == 0 for call in sleep.call_args_list)
    job.refresh_from_db()
    assert job.state == "succeeded"


@pytest.mark.django_db(transaction=True)
def test_synthetic_worker_keeps_its_demo_delay():
    seed(1)
    enqueue("demo-00001", str(uuid.uuid4()))
    with patch("librarium.management.commands.inspection_worker.time.sleep") as sleep:
        call_command("inspection_worker", once=True, step_seconds=0.25)
    assert [call.args[0] for call in sleep.call_args_list] == [0.25] * 4


@pytest.mark.django_db(transaction=True)
def test_concurrent_enqueues_create_one_active_review(tmp_path, settings):
    root = tmp_path / "catalogue"
    settings.LIBRARIUM_CATALOGUE_DIR = str(root)
    settings.LIBRARIUM_CATALOGUE_FIXTURE = False
    pin = build(root)
    shared = str(uuid.uuid4())

    def attempt(key):
        close_old_connections()
        try:
            return str(enqueue_catalogue(pin, key).pk)
        except CatalogueError as error:
            return error.status
        finally:
            close_old_connections()

    with ThreadPoolExecutor(4) as pool:
        distinct = list(pool.map(attempt, [str(uuid.uuid4()) for _ in range(4)]))
    assert len([r for r in distinct if isinstance(r, str)]) == 1
    assert sorted(r for r in distinct if not isinstance(r, str)) == [409, 409, 409]
    Job.objects.update(state="cancelled")
    with ThreadPoolExecutor(4) as pool:
        replayed = list(pool.map(attempt, [shared] * 4))
    assert len(set(replayed)) == 1 and isinstance(replayed[0], str)
    assert Job.objects.filter(kind="catalogue").count() == 2


@pytest.mark.django_db(transaction=True)
def test_two_workers_cannot_claim_the_same_review(tmp_path, settings):
    root = tmp_path / "catalogue"
    settings.LIBRARIUM_CATALOGUE_DIR = str(root)
    enqueue_catalogue(build(root), str(uuid.uuid4()))

    def worker():
        close_old_connections()
        try:
            item = claim()
            return str(item.pk) if item else None
        finally:
            close_old_connections()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert len([r for r in results if r]) == 1


@pytest.mark.django_db(transaction=True)
def test_migration_backfills_targets_and_reverses_only_without_reviews(tmp_path, settings):
    seed(1)
    executor = MigrationExecutor(connection)
    executor.migrate([("librarium", "0002_isolate_fixture_control")])
    old = (
        MigrationExecutor(connection)
        .loader.project_state(("librarium", "0002_isolate_fixture_control"))
        .apps
    )
    legacy = old.get_model("librarium", "Job").objects.create(
        work_id="demo-00001", request_key=uuid.uuid4(), input={}, input_fingerprint="x"
    )
    executor = MigrationExecutor(connection)
    executor.migrate([("librarium", "0003_catalogue_review_jobs")])
    migrated = Job.objects.get(pk=legacy.pk)
    assert (migrated.kind, migrated.target_id) == ("synthetic", "demo-00001")
    Job.objects.filter(pk=legacy.pk).update(state="succeeded")

    root = tmp_path / "catalogue"
    settings.LIBRARIUM_CATALOGUE_DIR = str(root)
    review = enqueue_catalogue(build(root), str(uuid.uuid4()))
    executor = MigrationExecutor(connection)
    with pytest.raises(Exception, match="catalogue review"):
        executor.migrate([("librarium", "0002_isolate_fixture_control")])
    assert Job.objects.filter(pk=review.pk).exists()

    historical = (
        MigrationExecutor(connection)
        .loader.project_state(("librarium", "0003_catalogue_review_jobs"))
        .apps.get_model("librarium", "Job")
    )
    historical.objects.filter(pk=review.pk).delete()
    executor = MigrationExecutor(connection)
    executor.migrate([("librarium", "0002_isolate_fixture_control")])
    executor = MigrationExecutor(connection)
    executor.migrate([("librarium", "0003_catalogue_review_jobs")])
    assert Job.objects.get(pk=legacy.pk).target_id == "demo-00001"
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
