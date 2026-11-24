"""Complete review history stays searchable beyond the live polling window."""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from librarium.models import Job
from librarium.seed import seed
from librarium.services import cancel, enqueue


def review(number, *, title=None, state="succeeded"):
    return Job.objects.create(
        id=uuid.UUID(int=number + 1),
        kind="catalogue",
        target_id=f"work-{number}",
        request_key=uuid.uuid4(),
        state=state,
        input_fingerprint="a" * 64,
        input={
            "title": title or f"Recorded title {number:03}",
            "source_version": "2026.10.24.2",
            "source_sha256": "b" * 64,
        },
        result={"findings": [{"message": "Captured evidence"}]},
    )


@pytest.mark.django_db
def test_history_pages_all_records_and_preserves_review_provenance(client):
    records = [review(number) for number in range(55)]
    when = timezone.now() - timedelta(days=2)
    Job.objects.all().update(created_at=when)
    pages = [client.get("/api/jobs/history", {"page": page}) for page in (1, 2, 3)]
    assert [page.status_code for page in pages] == [200, 200, 200]
    bodies = [page.json() for page in pages]
    assert [len(body["jobs"]) for body in bodies] == [24, 24, 7]
    assert [body["page"] for body in bodies] == [1, 2, 3]
    assert all(body["total"] == 55 and body["page_size"] == 24 for body in bodies)
    assert [job["id"] for body in bodies for job in body["jobs"]] == [
        str(record.pk) for record in reversed(records)
    ]
    old = bodies[-1]["jobs"][-1]
    assert (old["work_id"], old["source_version"], old["source_sha256"]) == (
        "work-0",
        "2026.10.24.2",
        "b" * 64,
    )
    assert old["result"] == records[0].result
    assert all(page.headers["Cache-Control"] == "no-store" for page in pages)
    assert client.get("/api/jobs/history?page=4").json() == {
        "jobs": [],
        "total": 55,
        "page": 4,
        "page_size": 24,
    }


@pytest.mark.django_db
def test_history_filters_kind_state_and_captured_title_without_losing_old_jobs(client):
    seed(1)
    synthetic = cancel(enqueue("demo-00001", str(uuid.uuid4())).pk)
    saved = review(1, title="The Old Chronicle", state="failed")
    review(2, title="The Old Chronicle", state="running")
    review(3, title="Another Chronicle", state="queued")
    review(4, title="New Chronicle")
    for number in range(5, 40):
        review(number)
    result = client.get(
        "/api/jobs/history", {"kind": "catalogue", "q": "  old CHRONICLE  ", "state": "failed"}
    ).json()
    assert result["total"] == 1
    assert [job["id"] for job in result["jobs"]] == [str(saved.pk)]
    active = client.get("/api/jobs/history?state=active").json()
    assert {job["state"] for job in active["jobs"]} == {"queued", "running"}
    assert active["total"] == 2
    demo = client.get("/api/jobs/history?kind=synthetic&state=cancelled").json()
    assert [job["id"] for job in demo["jobs"]] == [str(synthetic.pk)]
    assert client.get("/api/jobs/history?q=missing").json()["total"] == 0
    assert Job.objects.count() == 40


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["%", "_", "\\"])
def test_history_search_treats_sql_wildcards_literally(client, query):
    literal = review(1, title=f"A {query} Chronicle")
    review(2, title="A different Chronicle")
    body = client.get("/api/jobs/history", {"q": query}).json()
    assert body["total"] == 1
    assert [job["id"] for job in body["jobs"]] == [str(literal.pk)]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    [
        "?page=0",
        "?page=-1",
        "?page=10001",
        "?page=1.5",
        "?page=1&page=2",
        "?page=" + "9" * 5000,
        "?state=complete",
        "?state=Failed",
        "?state=failed&state=failed",
        "?kind=other",
        "?kind=catalogue&kind=synthetic",
        "?q=a&q=b",
        "?q=" + "a" * 201,
        "?q=bad%00",
        "?q=bad%0A",
        "?work_id=other",
        "?unknown=1",
    ],
    ids=[
        "page-zero",
        "page-negative",
        "page-too-large",
        "page-fraction",
        "page-duplicate",
        "page-oversized",
        "state-unknown",
        "state-wrong-case",
        "state-duplicate",
        "kind-unknown",
        "kind-duplicate",
        "query-duplicate",
        "query-oversized",
        "query-nul",
        "query-newline",
        "foreign-work",
        "unknown-param",
    ],
)
def test_history_rejects_bad_filters_before_database_access(
    client, django_assert_num_queries, query
):
    with django_assert_num_queries(0):
        result = client.get("/api/jobs/history" + query)
    assert result.status_code == 400
    assert "error" in result.json()


@pytest.mark.django_db
def test_empty_history_and_read_only_method(client):
    assert client.get("/api/jobs/history?kind=&q=&state=&page=10000").json() == {
        "jobs": [],
        "total": 0,
        "page": 10000,
        "page_size": 24,
    }
    assert (
        client.post("/api/jobs/history", "{}", content_type="application/json").status_code == 405
    )
    assert Job.objects.count() == 0
