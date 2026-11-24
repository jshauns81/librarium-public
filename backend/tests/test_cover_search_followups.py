"""Offline regressions for cover admission, history and catalogue absence."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from librarium import cover_sources as sources
from librarium.models import CoverSearch
from tests.test_web_cover_jobs import covers as covers_fixture
from tests.test_web_cover_jobs import library as library_fixture
from tests.test_web_cover_jobs import page as page_fixture
from tests.test_web_cover_jobs import setup_search as setup_search_fixture
from tests.test_web_cover_jobs import start

covers, library, page, setup_search = (
    covers_fixture,
    library_fixture,
    page_fixture,
    setup_search_fixture,
)


def metadata(source="hardcover", **extra):
    return {
        "src": sources.SOURCES[source],
        "title": "Synthetic One",
        "author": "Example Writer",
        "urls": ["https://assets.hardcover.app/cover.jpg"],
        **extra,
    }


def row():
    return SimpleNamespace(
        pk=uuid.uuid4(),
        entry=SimpleNamespace(title="Synthetic One", facts={}),
        request={},
        query={"title": "Synthetic One", "author": "Example Writer", "isbn": ""},
        candidates=[],
    )


@pytest.fixture
def lease(monkeypatch):
    manager = Mock()
    manager.filter.return_value.exists.return_value = True
    monkeypatch.setattr(sources, "CoverSearch", SimpleNamespace(objects=manager))
    return manager


@pytest.mark.parametrize(
    "image", ["https://unlisted.example.org/a.jpg", "https://assets.hardcover.app/a.jpg"]
)
def test_metadata_hit_without_admissible_image_is_empty(lease, monkeypatch, image):
    monkeypatch.setattr(
        sources,
        "source_search",
        lambda *a: {
            "state": "results",
            "candidates": [metadata(urls=[image])],
        },
    )
    monkeypatch.setattr(sources, "source_image", lambda *a: b"not an image")
    assert sources._run_source(row(), uuid.uuid4(), "hardcover") == ("empty", [])


@pytest.mark.parametrize("state", ["unavailable", "rate_limited", "timed_out", "failed", "partial"])
def test_source_failure_and_incomplete_coverage_remain_distinct(lease, monkeypatch, state):
    monkeypatch.setattr(sources, "source_search", lambda *a: {"state": state, "candidates": []})
    assert sources._run_source(row(), uuid.uuid4(), "hardcover") == (state, [])


def admitted(n):
    return {
        "id": str(n),
        "sha256": str(n) * 64,
        "title": "Synthetic One",
        "author": "Example Writer",
        "width": 600,
        "height": 900,
        "by_isbn": False,
        "_fp": {"g": [1.0], "c": [0.5]},
        "selectable": True,
        "reason": "Confirm visually.",
    }


def test_completion_order_does_not_change_rank_ties_and_failures_keep_other_art(lease, monkeypatch):
    from librarium.cover_source_fetch import SourceFailure

    second = threading.Event()
    finished = []

    def admit(item, *args):
        n = item["number"]
        if n == 1:
            assert second.wait(3)
        if n == 2:
            finished.append(n)
            second.set()
            return admitted(n)
        if n == 3:
            raise SourceFailure("unavailable")
        finished.append(n)
        return admitted(n)

    monkeypatch.setattr(sources, "admit", admit)
    monkeypatch.setattr(
        sources,
        "source_search",
        lambda *a: {
            "state": "results",
            "candidates": [metadata(number=n) for n in (1, 2, 3)],
        },
    )
    state, result = sources._run_source(row(), uuid.uuid4(), "hardcover")
    assert state == "partial" and [c["id"] for c in result] == ["1", "2"]
    assert finished == [2, 1]


def test_expired_slice_refuses_queued_image_before_fetch(lease, monkeypatch):
    monkeypatch.setattr(sources, "admit", lambda *a: pytest.fail("expired image fetched"))
    assert sources._admit_task(metadata(), row(), uuid.uuid4(), "hardcover", 0) == (
        "timed_out",
        None,
    )


def test_parallel_admission_is_bounded_and_keeps_provider_order(lease, monkeypatch):
    gate = threading.Barrier(3)
    lock = threading.Lock()
    active = peak = 0

    def admit(item, *args):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            gate.wait(timeout=3)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(sources, "admit", admit)
    monkeypatch.setattr(
        sources,
        "source_search",
        lambda *a: {
            "state": "results",
            "candidates": [metadata() for _ in range(6)],
        },
    )
    assert sources._run_source(row(), uuid.uuid4(), "hardcover") == ("empty", [])
    assert peak == 3 and active == 0


def test_queued_admissions_recheck_cancelled_lease(lease, monkeypatch):
    calls = []

    def admit(*args):
        calls.append(True)
        lease.filter.return_value.exists.return_value = False

    monkeypatch.setattr(sources, "admit", admit)
    monkeypatch.setattr(
        sources,
        "source_search",
        lambda *a: {
            "state": "results",
            "candidates": [metadata() for _ in range(6)],
        },
    )
    assert sources._run_source(row(), uuid.uuid4(), "hardcover") == ("cancelled", [])
    assert len(calls) <= 3


def test_admission_ceiling_is_shared_across_sources(lease, monkeypatch):
    active = peak = 0
    lock = threading.Lock()
    gate = threading.Barrier(3)

    def admit(*args):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            gate.wait(timeout=3)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(sources, "admit", admit)
    monkeypatch.setattr(
        sources,
        "source_search",
        lambda *a: {
            "state": "results",
            "candidates": [metadata() for _ in range(6)],
        },
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(sources._run_source, row(), uuid.uuid4(), source)
            for source in ("hardcover", "apple")
        ]
        assert [f.result() for f in futures] == [("empty", []), ("empty", [])]
    assert peak == 3 and active == 0


@pytest.mark.django_db(transaction=True)
def test_history_dedupes_content_newest_first_and_preserves_distinct_images(setup_search, client):
    url, params = setup_search
    start(client, url, params)
    first = CoverSearch.objects.get()
    first.state = "complete"
    first.candidates = [
        {
            "id": "old",
            "sha256": "a" * 64,
            "source_url": "https://example.org/one",
            "source_name": "Old",
            "match": 1,
        },
        {
            "id": "distinct",
            "sha256": "b" * 64,
            "source_url": "https://example.org/same",
            "match": 0.8,
        },
        {"id": "fallback-old", "source_url": "https://EXAMPLE.org:443/art", "match": 0},
    ]
    first.save()
    newest = CoverSearch.objects.create(
        entry=first.entry,
        binding=first.binding,
        request_key=uuid.uuid4(),
        actor=first.actor,
        request=first.request,
        query=first.query,
        sources=first.sources,
        statuses={"apple": "results"},
        state="complete",
    )
    newest.candidates = [
        {
            "id": "new",
            "sha256": "a" * 64,
            "source_url": "https://example.org/same",
            "source_name": "Newest",
            "match": 0.7,
        },
        {"id": "fallback-new", "source_url": "https://example.org/art", "match": 0},
    ]
    newest.save()
    result = sources.candidates(first.entry, first.binding)
    assert {c["id"] for c in result} == {"new", "distinct", "fallback-new"}
    assert next(c for c in result if c["id"] == "new")["source_name"] == "Newest"
    assert all(f"/{newest.pk}/" in c["url"] for c in result if c["id"] != "distinct")


@pytest.mark.django_db
def test_weak_catalogue_art_does_not_hide_exact_entry_absence(
    page, covers, settings, client, monkeypatch
):
    from librarium import cover_candidates
    from tests.test_cover_candidates import request, store

    store(covers, settings)
    url, params = request(page, client)
    monkeypatch.setattr(cover_candidates, "eligible_work", lambda match: None)
    reply = client.get(url, params, REMOTE_USER="reviewer")
    assert reply.status_code == 200
    assert reply.json()["candidates"]
    assert reply.json()["source"]["reason"] == "No exact catalogue entry."
    assert reply.json()["default_candidate_id"] is None


APPLE = "https://is1-ssl.mzstatic.com/image/thumb/{asset}/{size}x{size}bb.jpg"


class AppleFixture:
    """One synthetic Apple catalogue: the next search returns whatever `urls` names."""

    def __init__(self, monkeypatch, setup_search, client):
        from tests.test_cover_facts import jpeg

        self.url, self.params = setup_search
        self.client = client
        self.jpeg = jpeg
        self.rendition = {}
        self.assets = ["asset-a"]
        monkeypatch.setattr(sources, "source_search", self._search)
        monkeypatch.setattr(sources, "source_image", self._image)
        self.choices_url = self.url.removesuffix("/searches") + "/choices"

    def _search(self, query, *args):
        return {
            "state": "results",
            "candidates": [
                {
                    "src": "Apple Books",
                    "title": query["title"],
                    "author": query["author"],
                    "urls": [self.rendition[asset]],
                }
                for asset in self.assets
            ],
        }

    def _image(self, url, source):
        # Distinct pixels per rendition and per asset, so every record has its own bytes.
        wide = "3000x3000" in url
        width = (600 if wide else 400) + (0 if "asset-a" in url else 20)
        return self.jpeg((width, int(width * 1.5)), art=True)

    def search(self, **rendition):
        self.rendition.update(
            {asset: APPLE.format(asset=asset, size=size) for asset, size in rendition.items()}
        )
        self.assets = list(rendition)
        from tests.test_web_cover_jobs import start

        assert start(self.client, self.url, self.params).status_code in (200, 201, 202)
        sources.tick()

    def get(self):
        return self.client.get(self.choices_url, self.params, REMOTE_USER="reviewer").json()


@pytest.fixture
def apple(setup_search, client, monkeypatch):
    return AppleFixture(monkeypatch, setup_search, client)


def web(data):
    return [c for c in data["candidates"] if c["label"] == "Web"]


@pytest.mark.django_db(transaction=True)
def test_renditions_of_one_apple_artwork_are_one_choice_and_newest_wins(apple):
    apple.search(**{"asset-a": 3000})
    apple.search(**{"asset-a": 1600})
    data = apple.get()
    choices = web(data)
    assert len(choices) == 1
    assert "1600x1600bb" in choices[0]["source_url"]
    assert choices[0]["url"].split("/")[-2] == str(CoverSearch.objects.latest("created_at").pk)


@pytest.mark.django_db(transaction=True)
def test_different_apple_artwork_is_never_merged(apple):
    apple.search(**{"asset-a": 3000, "asset-b": 3000})
    apple.search(**{"asset-a": 1600})
    data = apple.get()
    urls = sorted(c["source_url"] for c in web(data))
    assert len(urls) == 2
    assert sum("asset-a" in u for u in urls) == 1
    assert sum("asset-b" in u for u in urls) == 1


@pytest.mark.django_db(transaction=True)
def test_saved_selection_of_older_rendition_stays_valid_and_selected(apple):
    from librarium.models import PreparedCover
    from tests.test_cover_candidates import choose

    apple.search(**{"asset-a": 3000})
    data = apple.get()
    old = web(data)[0]
    assert choose(apple.client, apple.choices_url, apple.params, data, old["id"]).status_code == 201
    saved = PreparedCover.objects.get()
    evidence = dict(saved.candidate)
    apple.search(**{"asset-a": 1600})
    data = apple.get()
    shown = web(data)
    assert len(shown) == 1
    assert shown[0]["id"] == old["id"] and shown[0]["sha256"] == old["sha256"]
    assert data["selection"]["status"] == "awaiting_approval"
    assert data["selection"]["candidate_id"] == shown[0]["id"]
    saved.refresh_from_db()
    assert saved.candidate == evidence
    assert sources.verify_candidate(saved.candidate)


@pytest.mark.django_db(transaction=True)
def test_saved_selection_survives_when_its_search_leaves_the_history_window(apple):
    from librarium.models import PreparedCover
    from tests.test_cover_candidates import choose

    apple.search(**{"asset-a": 3000})
    data = apple.get()
    old = web(data)[0]
    assert choose(apple.client, apple.choices_url, apple.params, data, old["id"]).status_code == 201
    evidence = dict(PreparedCover.objects.get().candidate)
    for _ in range(4):
        apple.search(**{"asset-a": 1600})
    data = apple.get()
    shown = web(data)
    assert len(shown) == 1 and shown[0]["id"] == old["id"]
    assert shown[0]["url"].split("/")[-2] == evidence["search_id"]
    assert data["selection"]["status"] == "awaiting_approval"
    assert data["selection"]["candidate_id"] == old["id"]
    assert PreparedCover.objects.get().candidate == evidence


@pytest.mark.django_db(transaction=True)
def test_selection_stays_on_its_own_record_beside_a_same_bytes_sibling(apple):
    from tests.test_cover_candidates import choose

    apple.search(**{"asset-a": 3000})
    data = apple.get()
    old = web(data)[0]
    assert choose(apple.client, apple.choices_url, apple.params, data, old["id"]).status_code == 201
    apple.search(**{"asset-a": 3000})
    data = apple.get()
    shown = web(data)
    assert len(shown) == 1
    assert shown[0]["id"] == old["id"] and shown[0]["sha256"] == old["sha256"]
    assert data["selection"]["candidate_id"] == old["id"]


def run_titles(monkeypatch, source, titles, known=(), **extra):
    """Offer these provider titles for "Synthetic One" and return what was admitted and shown."""
    fetched = []

    def admit(item, *args):
        fetched.append(item["title"])
        return {**admitted(len(fetched)), "title": item["title"]}

    monkeypatch.setattr(sources, "admit", admit)
    monkeypatch.setattr(
        sources,
        "source_search",
        lambda *a: {
            "state": "results",
            "candidates": [metadata(source, title=t, **extra) for t in titles],
        },
    )
    state, shown = sources._run_source(row(), uuid.uuid4(), source, None, lambda: list(known))
    return state, fetched, shown


@pytest.mark.parametrize("source", ["apple", "hardcover", "openlibrary"])
def test_unrelated_titles_are_not_fetched_or_offered(lease, monkeypatch, source):
    state, fetched, shown = run_titles(
        monkeypatch, source, ["Synthetic One", "A Completely Different Story", "Lantern of Ashes"]
    )
    assert fetched == ["Synthetic One"]
    assert state == "results" and [c["title"] for c in shown] == ["Synthetic One"]


def test_only_unrelated_titles_leave_an_empty_source(lease, monkeypatch):
    state, fetched, shown = run_titles(monkeypatch, "apple", ["A Completely Different Story"])
    assert (state, fetched, shown) == ("empty", [], [])


def test_omnibus_of_the_same_title_stays_for_the_kind_rule_to_refuse(lease, monkeypatch):
    _, fetched, _ = run_titles(monkeypatch, "apple", ["Synthetic One Omnibus"])
    assert fetched == ["Synthetic One Omnibus"]


def test_isbn_lookups_keep_their_provider_title(lease, monkeypatch):
    _, fetched, _ = run_titles(monkeypatch, "apple", ["Un Titre Etranger"], by_isbn=True)
    assert fetched == ["Un Titre Etranger"]


def test_decorated_title_is_a_weak_match_that_is_never_recommended(lease, monkeypatch):
    _, fetched, shown = run_titles(
        monkeypatch, "apple", ["Synthetic One: A Synthetic Saga Book 1", "Synthetic One"]
    )
    assert len(fetched) == 2
    exact, decorated = shown
    assert exact["title"] == "Synthetic One" and exact["recommended"]
    assert decorated["confidence"] == "possible" and not decorated.get("recommended")
    assert "weak" in decorated["reason"].lower()


def test_blank_query_title_filters_nothing(lease, monkeypatch):
    monkeypatch.setattr(sources, "admit", lambda item, *a: admitted(1))
    monkeypatch.setattr(
        sources,
        "source_search",
        lambda *a: {"state": "results", "candidates": [metadata("apple", title="Anything")]},
    )
    blank = row()
    blank.query = {**blank.query, "title": ""}
    assert sources._run_source(blank, uuid.uuid4(), "apple")[0] == "results"


TIMING_FIELDS = {"slot_wait_ms", "fetch_ms", "process_ms", "bytes", "attempts", "outcome"}


@pytest.mark.django_db(transaction=True)
def test_each_image_admission_is_timed_and_persisted_without_private_data(apple):
    import json

    apple.search(**{"asset-a": 1600, "asset-b": 1600})
    row = CoverSearch.objects.latest("created_at")
    timing = row.source_timings["apple"]
    assert timing["metadata_ms"] >= 0 and timing["admission_ms"] >= 0
    assert timing["finished_at"] and timing["duration_ms"] >= 0
    assert len(timing["images"]) == 2
    for image in timing["images"]:
        assert set(image) == TIMING_FIELDS
        assert image["outcome"] == "admitted" and image["attempts"] == 1 and image["bytes"] > 0
        assert all(type(image[k]) is int and image[k] >= 0 for k in TIMING_FIELDS - {"outcome"})
    stored = json.dumps(timing)
    assert "mzstatic" not in stored and "Synthetic" not in stored
    api = next(s for s in sources.data(row)["sources"] if s["id"] == "apple")
    assert api["images"] == timing["images"]


def test_fallback_attempts_and_rejected_images_are_counted(lease, monkeypatch, tmp_path, settings):
    from tests.test_cover_facts import jpeg

    settings.LIBRARIUM_ARTIFACT_DIR = str(tmp_path)
    good = jpeg((600, 900), art=True)
    calls = iter([b"not an image", good])
    monkeypatch.setattr(sources, "source_image", lambda *a: next(calls))
    monkeypatch.setattr(
        sources,
        "source_search",
        lambda *a: {
            "state": "results",
            "candidates": [
                metadata(
                    "apple",
                    urls=[
                        "https://is1-ssl.mzstatic.com/image/thumb/a/1600x1600bb.jpg",
                        "https://is1-ssl.mzstatic.com/image/thumb/b/1600x1600bb.jpg",
                    ],
                )
            ],
        },
    )
    timing = {}
    state, shown = sources._run_source(row(), uuid.uuid4(), "apple", timing)
    assert state == "results" and len(shown) == 1
    (image,) = timing["images"]
    assert image["attempts"] == 2 and image["bytes"] == len(good) and image["outcome"] == "admitted"


def test_slot_wait_is_measured_separately_from_fetch_and_decode(lease, monkeypatch):
    clock = iter(range(0, 10_000, 250))
    monkeypatch.setattr(sources, "_perf", lambda: next(clock) / 1000)
    monkeypatch.setattr(sources, "admit", lambda *a: None)
    record = sources._image_record()
    result = sources._admit_task(
        metadata(), row(), uuid.uuid4(), "hardcover", sources.time.monotonic() + 60, record
    )
    assert result == (None, None)
    assert record["slot_wait_ms"] == 250 and record["outcome"] == "rejected"


def test_timeouts_and_failures_are_recorded_per_image(lease, monkeypatch):
    from librarium.cover_source_fetch import SourceFailure

    def refuse(*a):
        raise SourceFailure("rate_limited")

    monkeypatch.setattr(sources, "admit", refuse)
    record = sources._image_record()
    far = sources.time.monotonic() + 60
    assert sources._admit_task(metadata(), row(), uuid.uuid4(), "hardcover", far, record) == (
        "rate_limited",
        None,
    )
    assert record["outcome"] == "rate_limited"
    expired = sources._image_record()
    sources._admit_task(metadata(), row(), uuid.uuid4(), "hardcover", 0, expired)
    assert expired["outcome"] == "timed_out"


def history_row(first, candidates):
    return CoverSearch.objects.create(
        entry=first.entry,
        binding=first.binding,
        request_key=uuid.uuid4(),
        actor=first.actor,
        request=first.request,
        query=first.query,
        sources=first.sources,
        statuses={"apple": "results"},
        state="complete",
        candidates=candidates,
    )


def record(name, sha, asset, size=1600, ext="jpg"):
    return {
        "id": name,
        "sha256": __import__("hashlib").sha256(sha.encode()).hexdigest(),
        "source_url": f"https://is1-ssl.mzstatic.com/image/thumb/{asset}/{size}x{size}bb.{ext}",
        "method": "web_original",
        "width": 600,
        "height": 900,
        "media_type": "image/jpeg",
        "selectable": True,
        "match": 1,
        "search_id": "unused",
    }


@pytest.mark.django_db(transaction=True)
def test_renditions_in_different_formats_are_still_one_artwork(setup_search, client):
    from tests.test_web_cover_jobs import start

    url, params = setup_search
    start(client, url, params)
    first = CoverSearch.objects.get()
    first.candidates = [record("old", "a", "asset-a", 3000, "webp")]
    first.save()
    history_row(first, [record("new", "b", "asset-a", 1600, "jpg")])
    assert [c["id"] for c in sources.candidates(first.entry, first.binding)] == ["new"]


@pytest.mark.django_db(transaction=True)
def test_artwork_replaced_at_one_path_never_hides_the_other_current_choice(setup_search, client):
    """An old record at path B carries the bytes of current artwork A, then B was replaced.

    Byte equality joins the old record to A. It must not also join A to B: both are current,
    different images, and a distinct image is never dropped for the sake of deduplication.
    """
    from tests.test_web_cover_jobs import start

    url, params = setup_search
    start(client, url, params)
    first = CoverSearch.objects.get()
    first.candidates = [record("old", "a", "asset-b")]
    first.save()
    history_row(first, [record("a", "a", "asset-a"), record("b", "b", "asset-b", 3000)])
    assert [c["id"] for c in sources.candidates(first.entry, first.binding)] == ["a", "b"]
    saved = SimpleNamespace(binding=first.binding, candidate=record("p", "p", "asset-b", 3000))
    saved.candidate["search_id"] = str(first.pk)
    shown = sources.candidates(first.entry, first.binding, saved)
    assert [c["id"] for c in shown] == ["a", "b", "p"]


def test_alias_of_the_matched_work_keeps_a_translated_title_as_a_weak_choice(lease, monkeypatch):
    state, fetched, shown = run_titles(
        monkeypatch, "apple", ["Un Titre Etranger"], known=["Synthetic One", "Un Titre Etranger"]
    )
    assert state == "results" and fetched == ["Un Titre Etranger"]
    (choice,) = shown
    assert choice["confidence"] == "possible" and "weak" in choice["reason"].lower()
    assert not choice.get("recommended")


@pytest.mark.parametrize(
    ("known", "found"),
    [
        (["Synthetic One", "It"], "It Came From Mars"),  # a short alias is not a substring licence
        (["Synthetic One", "The Stand"], "The Stand: Uncut Edition Companion Guide"),
        ([], "Un Titre Etranger"),  # no exact catalogue match: no alias evidence
    ],
)
def test_alias_evidence_needs_an_exactly_equal_title(lease, monkeypatch, known, found):
    state, fetched, shown = run_titles(monkeypatch, "apple", [found], known=known)
    assert (state, fetched, shown) == ("empty", [], [])


def test_exact_alias_equality_ignores_case_and_punctuation_only(lease, monkeypatch):
    _, fetched, _ = run_titles(monkeypatch, "apple", ["it"], known=["Synthetic One", "It"])
    assert fetched == ["it"]


def test_catalogue_evidence_is_resolved_once_per_search_and_only_when_needed(lease, monkeypatch):
    calls = []
    known = sources._Known(row())
    monkeypatch.setattr(
        sources.cover_candidates,
        "matched_work_titles",
        lambda entry, params: calls.append(1) or ["Un Titre Etranger"],
    )
    for source in ("apple", "hardcover"):
        run_titles_with(monkeypatch, source, ["Un Titre Etranger", "Synthetic One"], known)
    assert len(calls) == 1
    calls.clear()
    fresh = sources._Known(row())
    run_titles_with(monkeypatch, "apple", ["Synthetic One"], fresh)
    assert calls == []


def run_titles_with(monkeypatch, source, titles, known):
    monkeypatch.setattr(sources, "admit", lambda item, *a: {**admitted(1), "title": item["title"]})
    monkeypatch.setattr(
        sources,
        "source_search",
        lambda *a: {
            "state": "results",
            "candidates": [metadata(source, title=t) for t in titles],
        },
    )
    return sources._run_source(row(), uuid.uuid4(), source, None, known)


def drops(monkeypatch, titles, state="results", admit=None, known=None):
    """Run one Apple source over these provider titles; return (state, choices, timing)."""
    monkeypatch.setattr(
        sources, "admit", admit or (lambda item, *a: {**admitted(1), "title": item["title"]})
    )
    monkeypatch.setattr(
        sources,
        "source_search",
        lambda *a: {
            "state": state,
            "candidates": [metadata("apple", title=t) for t in titles],
        },
    )
    timing = {}
    result = sources._run_source(row(), uuid.uuid4(), "apple", timing, known)
    return (*result, timing)


def test_all_dropped_results_end_empty_with_every_result_counted(lease, monkeypatch):
    state, shown, timing = drops(
        monkeypatch,
        ["A Completely Different Story", "Lantern of Ashes"],
        admit=lambda *a: pytest.fail("fetched"),
    )
    assert (state, shown) == ("empty", [])
    assert timing["title_results"] == timing["title_mismatch"] == 2


def test_all_dropped_under_partial_keeps_the_upstream_partial_state(lease, monkeypatch):
    state, shown, timing = drops(
        monkeypatch,
        ["A Completely Different Story", "Lantern of Ashes"],
        state="partial",
        admit=lambda *a: pytest.fail("fetched"),
    )
    assert (state, shown) == ("partial", [])
    assert timing["title_results"] == timing["title_mismatch"] == 2


def test_a_matching_title_with_a_failed_image_is_not_counted_as_a_mismatch(lease, monkeypatch):
    state, shown, timing = drops(
        monkeypatch,
        ["Synthetic One", "Lantern of Ashes"],
        admit=lambda item, *a: None,  # the matching result's image is inadmissible
    )
    assert (state, shown) == ("empty", [])
    assert timing["title_results"] == 2 and timing["title_mismatch"] == 1


def test_nothing_dropped_counts_every_result_and_no_mismatch(lease, monkeypatch):
    state, shown, timing = drops(monkeypatch, ["Synthetic One"])
    assert state == "results" and len(shown) == 1
    assert timing["title_results"] == 1 and timing["title_mismatch"] == 0


def test_some_dropped_some_kept_still_reports_the_drops(lease, monkeypatch):
    state, shown, timing = drops(monkeypatch, ["Synthetic One", "Lantern of Ashes"])
    assert state == "results" and len(shown) == 1
    assert timing["title_results"] == 2 and timing["title_mismatch"] == 1


def test_a_weak_first_pick_does_not_suppress_a_stronger_recommendation(lease, monkeypatch):
    query_row = row()
    query_row.entry.title = "Xenos"
    query_row.query = {"title": "Xenos", "author": "Dan Abnett", "isbn": ""}

    def admit(item, *args):
        return {**admitted(len(item["title"])), "title": item["title"], "author": "Dan Abnett"}

    monkeypatch.setattr(sources, "admit", admit)
    monkeypatch.setattr(
        sources,
        "source_search",
        lambda *a: {
            "state": "results",
            "candidates": [
                metadata("apple", title="Eisenhorn: Xenos", author="Dan Abnett"),
                metadata("apple", title="Xenos", author="Dan Abnett"),
            ],
        },
    )
    _, shown = sources._run_source(query_row, uuid.uuid4(), "apple")
    picked = [c["title"] for c in shown if c.get("recommended")]
    assert picked == ["Xenos"]
    assert all(not c.get("recommended") for c in shown if c["title"] != "Xenos")


@pytest.fixture
def aliased_search(page, covers, settings, client, tmp_path):
    import sqlite3
    from contextlib import closing

    from tests.test_cover_candidates import request, store

    store(covers, settings)
    with closing(sqlite3.connect(covers[0])) as db, db:
        db.execute("INSERT INTO work_alias VALUES('w_fixture','Titre Etranger')")
    settings.LIBRARIUM_COVER_SOURCES_ENABLED = True
    settings.LIBRARIUM_ARTIFACT_DIR = str(tmp_path / "artifacts")
    (tmp_path / "artifacts").mkdir(mode=0o700)
    url, params = request(page, client)
    return url.removesuffix("/choices") + "/searches", params


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("found", "state", "choices", "dropped"),
    [
        ("Titre Etranger", "results", 1, 0),
        ("A Completely Different Story", "empty", 0, 1),
    ],
)
def test_translated_title_survives_only_with_catalogue_evidence(
    aliased_search, client, monkeypatch, found, state, choices, dropped
):
    from tests.test_cover_facts import jpeg
    from tests.test_web_cover_jobs import start

    url, params = aliased_search
    monkeypatch.setattr(
        sources,
        "source_search",
        lambda q, *a: {
            "state": "results",
            "candidates": [
                {
                    "src": "Apple Books",
                    "title": found,
                    "author": q["author"],
                    "urls": [APPLE.format(asset="asset-a", size=1600)],
                }
            ],
        },
    )
    monkeypatch.setattr(sources, "source_image", lambda *a: jpeg((600, 900), art=True))
    query = {"title": "Fixture Cover", "author": "Example Writer", "isbn": ""}
    assert start(client, url, params, query=query).status_code == 202
    sources.tick()
    row = CoverSearch.objects.get()
    assert row.statuses["apple"] == state and len(row.candidates) == choices
    assert row.source_timings["apple"]["title_mismatch"] == dropped
    assert row.source_timings["apple"]["title_results"] == 1
    api = next(s for s in sources.data(row)["sources"] if s["id"] == "apple")
    assert api["state"] == state and api["title_mismatch"] == dropped


@pytest.mark.django_db(transaction=True)
def test_full_picker_keeps_every_choice_when_the_saved_selection_matches_one(setup_search, client):
    from tests.test_web_cover_jobs import start

    url, params = setup_search
    start(client, url, params)
    first = CoverSearch.objects.get()
    first.candidates = [record(f"r0-{n}", f"{n:x}", f"asset-0-{n}") for n in range(6)]
    first.save()
    for row_number in range(1, 4):
        history_row(
            first,
            [
                record(f"r{row_number}-{n}", f"{row_number}{n:x}", f"asset-{row_number}-{n}")
                for n in range(6)
            ],
        )
    saved = SimpleNamespace(binding=first.binding, candidate=record("gone", "0", "asset-gone"))
    saved.candidate["search_id"] = str(first.pk)
    shown = sources.candidates(first.entry, first.binding, saved)
    assert len(shown) == sources.MAX_CANDIDATES == 24
    assert "gone" in [c["id"] for c in shown] and "r0-0" not in [c["id"] for c in shown]


# The previous release's picker rejects a whole progress response holding any other state.
PREVIOUS_RELEASE_STATES = frozenset(
    {
        "not_needed",
        "pending",
        "running",
        "results",
        "empty",
        "not_configured",
        "partial",
        "unavailable",
        "rate_limited",
        "timed_out",
        "failed",
        "cancelled",
        "challenged",
        "busy",
    }
)


@pytest.mark.django_db(transaction=True)
def test_a_title_mismatch_search_decodes_with_the_previous_releases_state_map(
    setup_search, client, monkeypatch
):
    from tests.test_web_cover_jobs import start

    url, params = setup_search
    monkeypatch.setattr(
        sources,
        "source_search",
        lambda *a: {
            "state": "results",
            "candidates": [metadata("apple", title="A Completely Different Story")],
        },
    )
    start(client, url, params)
    sources.tick()
    row = CoverSearch.objects.get()
    (apple,) = sources.data(row)["sources"]
    assert apple["state"] == "empty"
    assert apple["title_mismatch"] == apple["title_results"] == 1
    assert {s["state"] for s in sources.data(row)["sources"]} <= PREVIOUS_RELEASE_STATES
    assert set(sources.STATES) >= {"empty"} and "unmatched" not in sources.STATES


@pytest.mark.django_db(transaction=True)
def test_development_data_holding_unmatched_is_read_as_empty(setup_search, client):
    from tests.test_web_cover_jobs import start

    url, params = setup_search
    start(client, url, params)
    row = CoverSearch.objects.get()
    row.statuses = {"apple": "unmatched"}
    row.save()
    assert sources.data(row)["sources"][0]["state"] == "empty"
