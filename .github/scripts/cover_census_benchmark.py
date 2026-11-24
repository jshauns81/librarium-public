"""Offline, disposable cover-census fixture and profiler; never use a real library."""

import argparse
import cProfile
import hashlib
import io
import json
import os
import random
import runpy
import sqlite3
import time
import uuid
from pathlib import Path
from threading import Lock

MARKER = "synthetic-cover-census.json"


def hashes(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != MARKER
    }


def prepare(root, books, comment_bytes):
    from PIL import Image

    native = runpy.run_path(str(Path(__file__).with_name("native_library_acceptance.py")))
    native["prepare"](root, b"synthetic epub fixture")
    for path in root.glob("metadata.db*"):
        path.chmod(0o644)
    # Fold the fixture WAL into the disposable database before adding the census books.
    with sqlite3.connect(root / "metadata.db") as db:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("CREATE TABLE comments(id INTEGER PRIMARY KEY, book INTEGER, text TEXT)")
        rng = random.Random(19)
        covers = []
        for size in [(600, 900), (1000, 1500), (1200, 1600), (1600, 2400)]:
            image = Image.frombytes("RGB", (300, 450), rng.randbytes(300 * 450 * 3))
            image = image.resize(size)
            out = io.BytesIO()
            image.save(out, "JPEG", quality=90)
            covers.append(out.getvalue())
        for index in range(1, books + 1):
            folder = f"Synthetic Author/Fixture {index} ({index})"
            (root / folder).mkdir(parents=True)
            (root / folder / "cover.jpg").write_bytes(covers[index % len(covers)])
            if index == 1:
                db.execute("DELETE FROM books")
            db.execute(
                "INSERT INTO books VALUES(?,?,?,?,?,?,?)",
                (
                    index,
                    f"Fixture {index}",
                    f"Fixture {index}",
                    folder,
                    str(uuid.uuid5(uuid.NAMESPACE_OID, f"fixture-{index}")),
                    1,
                    None,
                ),
            )
            db.execute("INSERT INTO comments VALUES(?,?,?)", (index, index, "x" * comment_bytes))
        db.commit()
    manifest = {"books": books, "comment_bytes": comment_bytes, "hashes": hashes(root)}
    (root / MARKER).write_text(json.dumps(manifest))
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    print(
        json.dumps(
            {
                "books": books,
                "metadata_bytes": (root / "metadata.db").stat().st_size,
                "cover_bytes": [len(raw) for raw in covers],
            }
        )
    )


def run(root, profile, sample_ticks=0):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "librarium.settings")
    import django

    django.setup()
    from django.conf import settings
    from librarium import cover_reviews, library_read_model
    from librarium.models import CoverCensus, CoverReviewEntry, LibraryReadModel

    manifest = json.loads((root / MARKER).read_text())
    assert hashes(root) == manifest["hashes"]
    assert not CoverCensus.objects.exists() and not CoverReviewEntry.objects.exists()
    assert not LibraryReadModel.objects.exists(), "Use a fresh disposable application database"
    settings.DIRECT_LIBRARY_ROOT = str(root)
    settings.LIBRARY_READ_MODEL = "serve"
    library_read_model.refresh()
    library_read_model._next_tick = float("inf")
    census = cover_reviews.start(str(uuid.uuid4()))
    metrics = {}
    metrics_lock = Lock()
    for module, name in [
        (library_read_model, "current_token"),
        (cover_reviews, "source_facts"),
        (cover_reviews, "publish"),
        (cover_reviews, "recount"),
    ]:
        original = getattr(module, name)

        def measured(*args, _fn=original, _name=name, **kwargs):
            started = time.perf_counter()
            try:
                return _fn(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - started
                with metrics_lock:
                    value = metrics.setdefault(_name, {"calls": 0, "seconds": 0})
                    value["calls"] += 1
                    value["seconds"] += elapsed

        setattr(module, name, measured)
    profiler = cProfile.Profile()
    started = time.perf_counter()
    ticks = 0
    profiler.enable()
    while cover_reviews.tick():
        ticks += 1
        census.refresh_from_db()
        assert not census.error, census.error
        assert ticks < manifest["books"] * 3
        if sample_ticks and ticks >= sample_ticks:
            break
    profiler.disable()
    seconds = time.perf_counter() - started
    census.refresh_from_db()
    if not sample_ticks:
        assert census.state == "complete" and census.scanned == manifest["books"]
        assert census.remaining == census.unresolved == 0
        assert CoverReviewEntry.objects.count() == manifest["books"]
    assert hashes(root) == manifest["hashes"], "Synthetic library bytes changed"
    for entry in CoverReviewEntry.objects.all():
        index = entry.calibre_id
        assert entry.book_uuid == str(uuid.uuid5(uuid.NAMESPACE_OID, f"fixture-{index}"))
        relative = f"Synthetic Author/Fixture {index} ({index})/cover.jpg"
        assert entry.facts["sha256"] == manifest["hashes"][relative]
        assert (entry.facts["width"], entry.facts["height"]) == [
            (600, 900),
            (1000, 1500),
            (1200, 1600),
            (1600, 2400),
        ][index % 4]
    if profile:
        profiler.dump_stats(profile)
    print(
        json.dumps(
            {
                "books": census.scanned,
                "seconds": round(seconds, 3),
                "rows_per_second": round(census.scanned / seconds, 3),
                "ticks": ticks,
                "metrics": metrics,
                "state": census.state,
                "library_unchanged": True,
                "workers": settings.COVER_CENSUS_OBSERVATION_WORKERS,
                "cache": "warmed_by_input_verification_and_read_model_admission",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run"])
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--books", type=int, default=2000)
    parser.add_argument("--comment-bytes", type=int, default=32768)
    parser.add_argument("--profile")
    parser.add_argument("--sample-ticks", type=int, default=0)
    parser.add_argument("--require-read-only", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        assert 1 <= args.books <= 10000 and 0 <= args.comment_bytes <= 65536
        prepare(args.library, args.books, args.comment_bytes)
    else:
        if args.require_read_only:
            assert os.statvfs(args.library).f_flag & os.ST_RDONLY
        run(args.library, args.profile, args.sample_ticks)
