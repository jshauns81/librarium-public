import hashlib
import sqlite3
from contextlib import closing
from urllib.parse import parse_qs, urlsplit

import pytest
import test_catalogue_covers
from django.utils import timezone
from librarium import catalogue, catalogue_health, catalogue_status

cover_files = test_catalogue_covers.covers

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def fresh_snapshot_age(monkeypatch):
    monkeypatch.setattr(catalogue_health, "STALE_DAYS", 100)


def telemetry(**live):
    return {
        "state": "observed",
        "fetched_at": timezone.now().isoformat(),
        "age_seconds": 0,
        "failure": "",
        "status": {
            "live": {
                "state": "idle",
                "paused": False,
                "stalled": False,
                "next_cycle_at": "2026-11-10T13:00:00+00:00",
                **live,
            },
            "cycles": [],
            "snapshot": None,
        },
        "covers": {"upscale": {"failed": 0}},
    }


def test_headline_requires_fresh_live_evidence(monkeypatch, settings):
    settings.LIBRARIUM_CATALOGUE_DIR = ""
    monkeypatch.setattr(
        catalogue_status, "saved", lambda now: {"state": "unavailable", "reason": "Not configured"}
    )
    assert catalogue_health.build()["headline"]["level"] == "unavailable"


@pytest.mark.parametrize(
    "live,level",
    [
        ({}, "healthy"),
        ({"paused": True, "stalled": True}, "attention"),
        ({"state": "unknown"}, "unavailable"),
        ({"stalled": True, "state": "harvest"}, "stalled"),
        ({"state": "stopped"}, "attention"),
    ],
)
def test_live_headline(cover_files, monkeypatch, live, level):
    data = telemetry(**live)
    monkeypatch.setattr(catalogue_status, "saved", lambda now: data)
    report = catalogue_health.build()
    assert report["headline"]["level"] == level


def test_stale_status_mutes_last_known_failures(cover_files, monkeypatch):
    data = telemetry()
    data.update(state="stale", age_seconds=301)
    data["status"]["cycles"] = [{"tripped": ["publisher"], "stages": {}}]
    monkeypatch.setattr(catalogue_status, "saved", lambda now: data)
    assert catalogue_health.build()["headline"]["level"] == "stale"


def test_tripped_sources_and_failed_stages_raise_attention(cover_files, monkeypatch):
    data = telemetry()
    data["status"]["cycles"] = [
        {"tripped": ["publisher"], "stages": {"harvest": {"status": "error"}}}
    ]
    monkeypatch.setattr(catalogue_status, "saved", lambda now: data)
    report = catalogue_health.build()
    assert report["headline"]["level"] == "attention"
    assert "source" in " ".join(report["headline"]["reasons"])


def test_added_covers_use_ids_or_explicit_containment_never_title_matches(cover_files):
    path, _ = cover_files
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO work(id,title) VALUES ('w_child','Same title')")
        db.execute("INSERT INTO work(id,title) VALUES ('w_other','Same title')")
        db.execute("INSERT INTO work_contains VALUES ('w_fixture','w_child',1)")
    with catalogue.snapshot(str(path.parent), fixture=True) as (db, info):
        plates = catalogue_health.added_plates(db, info, ["w_child", "w_other", "w_fixture"])
        assert len(plates) == 1
        assert plates[0]["id"] == "w_child"
        assert plates[0]["collected_in"] == "Fixture Cover"
        assert "/w_fixture/" in plates[0]["cover"]["url"]
        assert catalogue_health.added_plates(db, info, ["w_other"]) == []


def test_derivative_examples_are_exact_pinned_local_bytes(cover_files, settings, client, tmp_path):
    path, _ = cover_files
    raw = test_catalogue_covers.png(2, 3)
    digest = hashlib.sha256(raw).hexdigest()
    root = tmp_path / "upscaled"
    target = root / digest[:2] / digest
    target.parent.mkdir(parents=True)
    target.write_bytes(raw)
    settings.LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR = str(root)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "INSERT INTO cover_derivative VALUES (?,'v1',?,2,3,'image/png','2026-11-10')",
            (test_catalogue_covers.DIGEST, digest),
        )
    with catalogue.snapshot(str(path.parent), fixture=True) as (db, info):
        examples = catalogue_health.upscaled_examples(db, info)
    assert len(examples) == 1
    cover = examples[0]["cover"]
    assert cover["sha256"] == digest and cover["upscaled"] is True
    assert parse_qs(urlsplit(cover["url"]).query)["variant"] == ["upscaled"]
    assert client.get(cover["url"]).content == raw
    settings.LIBRARIUM_CATALOGUE_COVER_DIR = ""
    assert client.get(cover["url"]).content == raw
    settings.LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR = ""
    assert client.get(cover["url"]).status_code == 503
    settings.LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR = str(root)
    target.write_bytes(b"changed")
    assert client.get(cover["url"]).status_code == 404


def test_shared_direct_art_is_labelled_as_the_containing_collection(cover_files):
    path, _ = cover_files
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT INTO work(id,title) VALUES ('w_child','A collected story')")
        db.execute("INSERT INTO work_contains VALUES ('w_fixture','w_child',1)")
        db.execute(
            "INSERT INTO work_cover SELECT 'w_child',source_url,sha256,width,height,media_type FROM work_cover WHERE work_id='w_fixture'"
        )
    with catalogue.snapshot(str(path.parent), fixture=True) as (db, info):
        plate = catalogue_health.added_plates(db, info, ["w_child"])[0]
    assert plate["collected_in"] == "Fixture Cover"


def test_first_remote_snapshot_does_not_claim_all_works_are_new(cover_files, monkeypatch):
    data = telemetry()
    data["status"]["snapshot"] = {
        "version": test_catalogue_covers.VERSION,
        "changes": {"first": True, "added_count": 1, "added": [{"id": "w_fixture"}]},
    }
    monkeypatch.setattr(catalogue_status, "saved", lambda now: data)
    assert catalogue_health.build()["lately"]["state"] == "unavailable"
