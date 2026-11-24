"""HTTP boundary for catalogue metadata reviews, alongside the synthetic inspections."""

import uuid

import pytest
from django.test import Client
from librarium.models import Job, Work
from librarium.seed import seed
from librarium.services import cancel, enqueue
from test_catalogue_reviews import VERSION, WORK, build, run, snapshot  # noqa: F401


def post(client, body, key=None, **headers):
    if key is not None:
        headers["HTTP_IDEMPOTENCY_KEY"] = key
    return client.post("/api/jobs", body, content_type="application/json", **headers)


def listed(client, query=""):
    return {job["id"]: job for job in client.get(f"/api/jobs{query}").json()["jobs"]}


@pytest.fixture
def pin(db, snapshot):  # noqa: F811
    seed(40)
    return build(snapshot)


def test_review_requires_csrf_and_serializes_its_provenance(pin):
    strict = Client(enforce_csrf_checks=True)
    assert post(strict, pin, str(uuid.uuid4())).status_code == 403
    assert Job.objects.count() == 0
    token = strict.get("/api/session").json()["csrf"]
    result = post(strict, pin, str(uuid.uuid4()), HTTP_X_CSRFTOKEN=token)
    assert result.status_code == 202
    job = result.json()
    stored = Job.objects.get(pk=job["id"])
    assert job["kind"] == "catalogue"
    assert job["work_id"] == WORK
    assert job["title"] == "Fixture: The Review"
    assert job["state"] == "queued"
    assert job["source_version"] == VERSION
    assert job["source_sha256"] == pin["sha256"]
    assert job["input_fingerprint"] == stored.input_fingerprint
    assert result.headers["Cache-Control"] == "no-store"
    url = f"/api/jobs/{job['id']}"
    assert strict.post(url, "{}", content_type="application/json").status_code == 403
    assert Job.objects.get(pk=job["id"]).state == "queued"


def test_review_never_inserts_or_targets_a_collection_work(pin, client):
    before = sorted(Work.objects.values_list("pk", flat=True))
    job = post(client, pin, str(uuid.uuid4())).json()
    assert sorted(Work.objects.values_list("pk", flat=True)) == before
    stored = Job.objects.get(pk=job["id"])
    assert (stored.kind, stored.work_id, stored.target_id) == ("catalogue", None, WORK)


@pytest.mark.parametrize("key", [None, "", "not-a-uuid", "1" * 37])
def test_missing_or_bad_request_key_is_rejected(pin, client, key):
    result = post(client, pin, key)
    assert result.status_code == 400
    assert result.json()["error"] == "Use a valid request key"
    assert Job.objects.count() == 0


def test_replay_returns_the_same_review_and_conflicts_are_409(pin, client):
    key = str(uuid.uuid4())
    first = post(client, pin, key)
    replay = post(client, pin, key)
    assert (first.status_code, replay.status_code) == (202, 202)
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["revision"] == first.json()["revision"]
    assert post(client, {**pin, "sha256": "b" * 64}, key).status_code == 409
    active = post(client, pin, str(uuid.uuid4()))
    assert active.status_code == 409
    assert "active review" in active.json()["error"]
    synthetic = enqueue("demo-00001", str(uuid.uuid4()))
    assert post(client, pin, str(synthetic.request_key)).status_code == 409
    assert Job.objects.filter(kind="catalogue").count() == 1


def test_replay_survives_an_unmounted_catalogue_but_new_requests_do_not(pin, client, settings):
    key = str(uuid.uuid4())
    job = post(client, pin, key).json()
    settings.LIBRARIUM_CATALOGUE_DIR = ""
    replay = post(client, pin, key)
    assert replay.status_code == 202
    assert replay.json()["id"] == job["id"]
    cancel(job["id"])
    fresh = post(client, pin, str(uuid.uuid4()))
    assert fresh.status_code >= 400
    assert "error" in fresh.json()
    assert Job.objects.filter(kind="catalogue").count() == 1


def test_stale_or_unknown_pins_are_refused_without_queueing(pin, client, snapshot):  # noqa: F811
    unknown = post(client, {**pin, "catalogue_work_id": "missing"}, str(uuid.uuid4()))
    assert unknown.status_code == 404
    build(snapshot, editions=[])  # same version file, different bytes
    stale = post(client, pin, str(uuid.uuid4()))
    assert stale.status_code == 409
    assert Job.objects.count() == 0


@pytest.mark.parametrize(
    "body",
    [
        lambda pin: {**pin, "work_id": "demo-00001"},
        lambda pin: {**pin, "extra": True},
        lambda pin: {"catalogue_work_id": WORK, "version": pin["version"]},
        lambda pin: {**pin, "version": 20261025},
        lambda pin: {**pin, "sha256": pin["sha256"].upper()},
        lambda pin: {"work_id": "demo-00001", "version": pin["version"], "sha256": pin["sha256"]},
        lambda pin: {"work_id": "demo-00001", "kind": "catalogue"},
        lambda pin: [pin],
    ],
)
def test_mixed_partial_or_extra_payloads_are_bad_requests(pin, client, body):
    result = post(client, body(pin), str(uuid.uuid4()))
    assert result.status_code == 400
    assert "error" in result.json()
    assert Job.objects.count() == 0


def test_malformed_json_is_a_bad_request(pin, client):
    result = post(client, "{", str(uuid.uuid4()))
    assert result.status_code == 400
    assert Job.objects.count() == 0


def test_synthetic_requests_keep_their_contract(pin, client):
    result = post(client, {"work_id": "demo-00001"}, str(uuid.uuid4()))
    assert result.status_code == 202
    job = result.json()
    assert (job["kind"], job["work_id"], job["source_sha256"]) == (
        "synthetic",
        "demo-00001",
        None,
    )
    assert post(client, {"work_id": "missing"}, str(uuid.uuid4())).status_code == 404
    assert post(client, {"work_id": "demo-00001"}, "bad").status_code == 400


def test_cancel_is_shared_and_keeps_review_provenance(pin, client):
    job = post(client, pin, str(uuid.uuid4())).json()
    url = f"/api/jobs/{job['id']}"
    assert client.post(url, '{"x":1}', content_type="application/json").status_code == 400
    first = client.post(url, "{}", content_type="application/json").json()
    second = client.post(url, "{}", content_type="application/json").json()
    assert first["state"] == "cancelled"
    assert second["revision"] == first["revision"] == job["revision"] + 1
    assert (first["kind"], first["work_id"], first["source_sha256"]) == (
        "catalogue",
        WORK,
        pin["sha256"],
    )
    assert client.get(url).json() == second
    assert post(client, pin, str(uuid.uuid4())).status_code == 202


@pytest.mark.parametrize(
    "query",
    [
        "?kind=other",
        "?kind=Catalogue",
        "?kind=catalogue&kind=synthetic",
        "?kind=catalogue&kind=catalogue",
        "?work_id=a&work_id=b",
        "?unknown=1",
        "?work_id=" + "x" * 81,
        "?work_id=a%00",
    ],
)
def test_job_list_rejects_unknown_duplicate_or_oversized_filters(db, client, query):
    assert client.get(f"/api/jobs{query}").status_code == 400


def test_job_list_accepts_an_eighty_character_target(db, client):
    assert client.get("/api/jobs?work_id=" + "x" * 80).json() == {"jobs": []}
    assert client.get("/api/jobs?kind=&work_id=").status_code == 200


def test_kind_filter_isolates_reviews_and_keeps_old_selected_results(pin, client):
    review = run(uuid.UUID(post(client, pin, str(uuid.uuid4())).json()["id"]))
    assert review.state == "succeeded"
    for number in range(2, 35):
        cancel(enqueue(f"demo-{number:05}", str(uuid.uuid4())).pk)
    old = str(review.pk)
    everything = listed(client)
    assert old not in everything
    assert len(everything) == 30
    catalogue = listed(client, "?kind=catalogue")
    assert list(catalogue) == [old]
    assert catalogue[old]["result"] == review.result
    assert catalogue[old]["source_sha256"] == pin["sha256"]
    synthetic = listed(client, "?kind=synthetic")
    assert old not in synthetic
    assert {job["kind"] for job in synthetic.values()} == {"synthetic"}
    assert old in listed(client, f"?work_id={WORK}")
    assert old in listed(client, f"?kind=catalogue&work_id={WORK}")
    assert old not in listed(client, f"?kind=synthetic&work_id={WORK}")
    assert set(listed(client, "?kind=catalogue&work_id=demo-00002")) == {old}


def test_selected_synthetic_work_matches_legacy_rows_without_a_target(pin, client):
    legacy = enqueue("demo-00001", str(uuid.uuid4()))
    cancel(legacy.pk)
    Job.objects.filter(pk=legacy.pk).update(target_id="")
    for number in range(2, 35):
        cancel(enqueue(f"demo-{number:05}", str(uuid.uuid4())).pk)
    selected = listed(client, "?kind=synthetic&work_id=demo-00001")
    assert selected[str(legacy.pk)]["work_id"] == "demo-00001"
    assert str(legacy.pk) not in listed(client, "?kind=catalogue&work_id=demo-00001")
