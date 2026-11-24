import json
import sqlite3
import uuid
from contextlib import closing
from datetime import timedelta

import pytest
import test_catalogue
from django.utils import timezone
from librarium import catalogue_health
from librarium.models import Job

catalogue = test_catalogue.catalogue
pytestmark = pytest.mark.django_db(transaction=True)
# Dated from today so the fixtures are never stale; the age tests pin their own clock.
NOW = timezone.now()
TODAY = NOW.date()
OLD = (TODAY - timedelta(days=1)).strftime("%Y.%m.%d") + ".1"
NEW = TODAY.strftime("%Y.%m.%d") + ".1"


@pytest.fixture(autouse=True)
def fresh_cache():
    catalogue_health._cache.clear()
    yield
    catalogue_health._cache.clear()


@pytest.fixture
def snapshots(tmp_path, settings):
    root = tmp_path / "catalogue"
    old = test_catalogue.make_snapshot(root, OLD, title="Fixture: The Old Meridian")
    new = test_catalogue.make_snapshot(root, NEW)
    settings.LIBRARIUM_CATALOGUE_DIR = str(root)
    settings.LIBRARIUM_CATALOGUE_FIXTURE = True
    settings.LIBRARIUM_CATALOGUE_COVER_DIR = ""
    return root, old, new


def write(path, *statements):
    with closing(sqlite3.connect(path)) as db, db:
        for statement in statements:
            if isinstance(statement, tuple):
                db.execute(*statement)
            else:
                db.execute(statement)


def health(client):
    reply = client.get("/api/catalogue/health")
    assert reply.status_code == 200
    return reply.json()


def record(source, native_id, fetched_at):
    return (
        (
            "INSERT INTO source_record(source,native_id,fetched_at,parsed_json,content_hash,"
            "last_seen_at) VALUES (?,?,?,'{}',?,?)"
        ),
        (source, native_id, fetched_at, native_id, fetched_at),
    )


def logged(source, query, status, fetched_at):
    return (
        "INSERT INTO harvest_log(source,query,status,http_status,fetched_at) VALUES (?,?,?,NULL,?)",
        (source, query, status, fetched_at),
    )


def test_unconfigured_catalogue_reports_every_section_unavailable(client, settings):
    settings.LIBRARIUM_CATALOGUE_DIR = ""
    data = health(client)
    assert data["saved_headline"]["level"] == "unavailable"
    for name in ("harvester", "changes", "size", "covers", "cycles", "controls"):
        assert data[name]["state"] == "unavailable"
        assert data[name]["reason"]
    assert data["librarium"]["snapshot"]["state"] == "unavailable"


def test_clients_are_named_and_never_given_numbers(client, settings):
    settings.LIBRARIUM_CATALOGUE_DIR = ""
    clients = health(client)["clients"]
    assert [c["name"] for c in clients] == [
        "BLC Lexicanum Chrome extension",
        "Library Finish Cover Art Chrome extension",
        "BLC Calibre plugin",
    ]
    assert {c["state"] for c in clients} == {"unavailable"}
    assert all(set(c) == {"id", "name", "state", "reason"} for c in clients)


def test_size_matches_blc_status_totals(client, snapshots):
    _, _, new = snapshots
    write(
        new,
        "UPDATE work SET type='novel'",
        "INSERT INTO work(id,title,type,synopsis) VALUES ('w2','Second','novel','')",
        "INSERT INTO work(id,title) VALUES ('w3','Third')",
        "INSERT INTO edition(id,work_id,format,isbn13) VALUES ('e2','w_fixture','audiobook','9780306406164')",
        "INSERT INTO edition(id,work_id,format) VALUES ('e3','w2',NULL)",
    )
    size = health(client)["size"]
    assert size == {
        "state": "observed",
        "works": 3,
        "editions": 3,
        "authors": 1,
        "series": 1,
        "by_type": [{"name": "novel", "count": 2}, {"name": "unknown", "count": 1}],
        "by_format": [
            {"name": "audiobook", "count": 1},
            {"name": "ebook", "count": 1},
            {"name": "unknown", "count": 1},
        ],
        "with_isbn": 1,
        "with_synopsis": 1,
    }


def test_changes_count_added_removed_merged_and_retitled(client, snapshots):
    _, old, new = snapshots
    write(
        old,
        "INSERT INTO work(id,title) VALUES ('gone','Removed work')",
        "INSERT INTO work(id,title) VALUES ('merged','Merged work')",
    )
    write(
        new,
        "INSERT INTO work(id,title,type) VALUES ('fresh','A fresh work','novel')",
        "INSERT INTO id_alias VALUES ('merged','w_fixture')",
    )
    changes = health(client)["changes"]
    assert changes["from_version"] == OLD
    assert changes["to_version"] == NEW
    assert (
        changes["added_count"],
        changes["removed_count"],
        changes["merged_count"],
        changes["retitled_count"],
    ) == (1, 1, 1, 1)
    assert changes["added"] == [
        {"id": "fresh", "title": "A fresh work", "type": "novel", "cover": None}
    ]
    assert changes["removed"] == [{"id": "gone", "title": "Removed work", "type": None}]
    assert changes["retitled"] == [
        {
            "id": "w_fixture",
            "from": "Fixture: The Old Meridian",
            "to": "Fixture: The Glass Meridian",
        }
    ]


def test_single_kept_snapshot_does_not_claim_everything_is_new(client, catalogue):
    changes = health(client)["changes"]
    assert changes["state"] == "unavailable"
    assert "No earlier snapshot" in changes["reason"]


def test_unreadable_previous_snapshot_is_named_not_hidden(client, snapshots):
    _, old, _ = snapshots
    old.write_bytes(b"not a database")
    data = health(client)
    assert data["changes"] == {
        "state": "unavailable",
        "reason": f"The previous snapshot {OLD} could not be read.",
    }
    assert data["size"]["state"] == "observed"


def test_harvest_counts_only_the_window_since_the_previous_snapshot(client, snapshots):
    _, old, new = snapshots
    before, after = "2026-10-24T10:00:00+00:00", "2026-10-25T09:00:00+00:00"
    write(old, logged("lexicanum", "q-old", "ok", before))
    write(
        new,
        logged("lexicanum", "q-old", "ok", before),
        logged("lexicanum", "private query text", "ok", after),
        logged("lexicanum", "q-err", "error", "2026-10-25T09:30:00+00:00"),
        logged("publisher", "q-pub", "ok", after),
        record("lexicanum", "old-record", before),
        record("lexicanum", "new-record", after),
    )
    data = health(client)
    harvester = data["harvester"]
    assert harvester["window"] == {"since": before, "since_version": OLD}
    assert harvester["sources"] == [
        {
            "source": "lexicanum",
            "asked": 2,
            "new_records": 1,
            "errors": 1,
            "last_at": "2026-10-25T09:30:00+00:00",
            "last_status": "error",
        },
        {
            "source": "publisher",
            "asked": 1,
            "new_records": 0,
            "errors": 0,
            "last_at": after,
            "last_status": "ok",
        },
    ]
    assert harvester["last_recorded_at"] == "2026-10-25T09:30:00+00:00"
    assert harvester["last_recorded_age_seconds"] > 0
    assert harvester["live"]["state"] == "unavailable"
    assert harvester["tripped"]["state"] == "unavailable"
    assert harvester["budget_deferred"]["state"] == "unavailable"
    assert "private query text" not in json.dumps(data)
    assert data["saved_headline"]["level"] == "attention"
    assert any("1 harvest requests" in r for r in data["saved_headline"]["reasons"])


def test_harvest_without_a_previous_snapshot_covers_everything_recorded(client, catalogue):
    _, path = catalogue
    write(path, logged("lexicanum", "q", "ok", "2026-10-20T00:00:00+00:00"))
    harvester = health(client)["harvester"]
    assert harvester["window"] == {"since": None, "since_version": None}
    assert harvester["sources"][0]["asked"] == 1


def test_errors_in_all_recorded_history_are_shown_but_do_not_raise_attention(client, snapshots):
    root, _, new = snapshots
    (root / f"{OLD}.sqlite").unlink()
    write(new, logged("lexicanum", "q", "error", "2026-01-01T00:00:00+00:00"))
    data = health(client)
    assert data["harvester"]["window"]["since"] is None
    assert data["harvester"]["sources"][0]["errors"] == 1
    assert data["saved_headline"]["level"] == "healthy"


def test_covers_and_upscale_queue_come_from_snapshot_tables(client, catalogue):
    _, path = catalogue
    digest = "a" * 64
    write(
        path,
        f"INSERT INTO cover_asset VALUES ('https://example.com/a.jpg','{digest}',600,900,'image/jpeg')",
        "INSERT INTO cover_asset VALUES ('https://example.com/b.jpg','"
        + "b" * 64
        + "',600,900,'image/jpeg')",
        f"INSERT INTO work_cover VALUES ('w_fixture','https://example.com/a.jpg','{digest}',600,900,'image/jpeg')",
        f"INSERT INTO cover_derivative VALUES ('{digest}','v1','"
        + "c" * 64
        + "',1200,1800,'image/png','2026-10-25')",
        "INSERT INTO cover_upscale_job VALUES ('1','v1','pending',0,0,'t',NULL)",
        "INSERT INTO cover_upscale_job VALUES ('2','v1','pending',2,0,'t','x')",
        "INSERT INTO cover_upscale_job VALUES ('3','v1','running',1,0,'t',NULL)",
        "INSERT INTO cover_upscale_job VALUES ('4','v1','failed',3,0,'t','x')",
        "INSERT INTO cover_upscale_job VALUES ('5','v1','done',1,0,'t',NULL)",
    )
    data = health(client)
    covers = data["covers"]
    assert (covers["saved"], covers["works_with_covers"]) == (2, 1)
    for name in ("awaiting", "failed", "last_download"):
        assert covers[name]["state"] == "unavailable"
    upscale = covers["upscale"]
    assert {k: upscale[k] for k in ("upscaled", "awaiting", "retry", "running", "failed")} == {
        "upscaled": 1,
        "awaiting": 1,
        "retry": 1,
        "running": 1,
        "failed": 1,
    }
    assert upscale["paused"]["state"] == "unavailable"
    assert "1 cover upscales failed." in data["saved_headline"]["reasons"]


def test_snapshot_without_cover_tables_is_unavailable(client, catalogue):
    _, path = catalogue
    write(path, "DROP TABLE work_cover")
    covers = health(client)["covers"]
    assert covers == {"state": "unavailable", "reason": "This snapshot carries no cover records."}


def test_librarium_flags_a_newer_saved_snapshot(client, snapshots):
    root, _, _ = snapshots
    (root / "current").write_text(OLD)
    data = health(client)
    snapshot = data["librarium"]["snapshot"]
    assert snapshot["pinned"]["version"] == OLD
    assert snapshot["latest_available"] == NEW
    assert snapshot["behind"] is True
    assert snapshot["dated"] == (TODAY - timedelta(days=1)).isoformat()
    assert snapshot["kept"] == [NEW, OLD]
    assert data["saved_headline"]["level"] == "attention"
    assert NEW in data["saved_headline"]["reasons"][0]
    # Serving the older snapshot, there is no earlier one to compare with.
    assert data["changes"]["state"] == "unavailable"


def test_snapshot_age_counts_days_from_its_version_date(snapshots):
    now = NOW + timedelta(days=7)
    data = catalogue_health.build(now)
    snapshot = data["librarium"]["snapshot"]
    assert (snapshot["age_days"], snapshot["behind"], snapshot["stale"]) == (7, False, False)
    assert snapshot["stale_after_days"] == 7
    assert data["saved_headline"]["level"] == "healthy"


def test_snapshot_older_than_a_week_needs_attention(snapshots):
    data = catalogue_health.build(NOW + timedelta(days=8))
    assert data["librarium"]["snapshot"]["stale"] is True
    assert data["saved_headline"]["level"] == "attention"
    assert data["saved_headline"]["reasons"][0] == (
        "The served snapshot is 8 days old; snapshots older than 7 days need attention."
    )


def test_last_sync_is_unavailable_until_reference_imports_run(client, snapshots, settings):
    settings.LIBRARIUM_REFERENCE_STATE_DIR = ""
    sync = health(client)["librarium"]["last_sync"]
    assert sync["state"] == "unavailable"
    assert "not running inside Librarium" in sync["reason"]


def make_job(state, **fields):
    return Job.objects.create(
        kind="epub",
        target_id=uuid.uuid4().hex * 2,
        request_key=uuid.uuid4(),
        input_fingerprint="a" * 64,
        input={},
        state=state,
        **fields,
    )


def test_job_health_counts_active_expired_and_recent_failures(client, snapshots):
    make_job("queued")
    make_job("running", lease_until=timezone.now() - timedelta(minutes=5))
    make_job("failed")
    old_failure = make_job("failed")
    Job.objects.filter(pk=old_failure.pk).update(updated_at=timezone.now() - timedelta(days=3))
    data = health(client)
    jobs = data["librarium"]["jobs"]
    assert (jobs["queued"], jobs["running"], jobs["expired_leases"]) == (1, 1, 1)
    assert jobs["failed_last_day"] == 1
    assert jobs["latest_failure"]["kind"] == "epub"
    assert data["saved_headline"]["level"] == "attention"
    assert "1 running jobs are past their lease." in data["saved_headline"]["reasons"]
    assert "1 jobs failed in the last day." in data["saved_headline"]["reasons"]


def test_healthy_headline_is_scoped_to_what_librarium_sees(client, snapshots):
    data = health(client)
    assert data["saved_headline"]["level"] == "healthy"
    assert NEW in data["saved_headline"]["reasons"][0]
    assert "saved evidence" in data["saved_headline"]["reasons"][0]
    jobs = data["librarium"]["jobs"]
    assert (jobs["queued"], jobs["failed_last_day"], jobs["latest_failure"]) == (0, 0, None)


def test_report_follows_a_changed_snapshot(client, catalogue):
    _, path = catalogue
    assert health(client)["size"]["works"] == 1
    write(path, "INSERT INTO work(id,title) VALUES ('w2','Second')")
    assert health(client)["size"]["works"] == 2


def test_parameters_are_rejected(client, catalogue):
    assert client.get("/api/catalogue/health", {"version": NEW}).status_code == 400
    assert client.post("/api/catalogue/health").status_code in {403, 405}


def test_oversized_source_names_fail_closed(client, catalogue):
    _, path = catalogue
    write(path, logged("x" * 101, "q", "ok", "2026-10-25T00:00:00+00:00"))
    data = health(client)
    assert data["harvester"]["state"] == "unavailable"
    assert "dashboard limit" in data["harvester"]["reason"]
    assert data["saved_headline"]["level"] == "unavailable"


@pytest.mark.parametrize("matching", [True, False])
def test_publication_age_belongs_to_the_reported_version(matching):
    report = {
        "librarium": {
            "snapshot": {
                "state": "observed",
                "pinned": {"version": OLD},
                "age_days": 1,
                "stale": False,
                "behind": False,
            },
            "catalogue_sync": {
                "published_version": NEW if matching else OLD,
                "published_created_at": NOW.isoformat(),
            },
            "last_sync": {"state": "unavailable"},
            "jobs": {"state": "unavailable", "reason": "No observation"},
        },
        "telemetry": {"status": {"published_version": NEW}},
        "harvester": {"state": "unavailable"},
        "covers": {},
    }
    reasons = " ".join(catalogue_health.snapshot_headline(report)["reasons"])
    assert ("Publication time is not reported." in reasons) == (not matching)
    assert ("seconds ago." in reasons) == matching
