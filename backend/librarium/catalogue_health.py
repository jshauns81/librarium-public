"""Catalogue evidence and the latest worker-polled BLC status; no request-time network IO."""

import copy
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone
from django.views.decorators.http import require_GET

from librarium import (
    catalogue,
    catalogue_covers,
    catalogue_status,
    catalogue_sync,
    operational_status,
    reference_production,
)
from librarium.models import Job
from librarium.views import response

SHOWN = 12
# BL Catalog publishes every 6 hours when content changes; a week without one is stale.
STALE_DAYS = 7
SOURCE_LIMIT = 64
CACHE_LIMIT = 4
NOT_LIVE = (
    "BL Catalog's live harvester status is not reported to Librarium yet; "
    "Librarium reads saved snapshots only."
)
NO_CYCLES = (
    "BL Catalog keeps its cycle log beside the harvester; it is not reported to Librarium yet."
)
NO_INBOX = "BL Catalog's cover inbox is not reported to Librarium yet."
NO_CONTROLS = (
    "Scan, cover pass and upscale controls belong to BL Catalog's own status page. "
    "Open the configured status page to use those controls."
)
CLIENTS = (
    ("lexicanum_extension", "BLC Lexicanum Chrome extension"),
    ("cover_art_extension", "Library Finish Cover Art Chrome extension"),
    ("calibre_plugin", "BLC Calibre plugin"),
)
NOT_REPORTED = "Not reported yet: this client sends Librarium no version or activity."

_cache: dict[tuple, dict] = {}


def unavailable(reason: str) -> dict:
    return {"state": "unavailable", "reason": reason}


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def saved_versions(directory: Path) -> list[str]:
    """Published snapshot versions kept in the catalogue directory, oldest first."""
    names = (
        path.name.removesuffix(".sqlite")
        for path in directory.glob("*.sqlite")
        if path.is_file() and not path.is_symlink()
    )
    return sorted((name for name in names if catalogue.valid_version(name)), key=version_key)


def tables(db) -> set[str]:
    return {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}


def size(db) -> dict:
    """Totals of the snapshot, as BL Catalog's status page counts them."""

    def grouped(sql: str) -> list[dict]:
        totals = [(name or "unknown", count) for name, count in db.execute(sql)]
        return [{"name": n, "count": c} for n, c in sorted(totals, key=lambda t: (-t[1], t[0]))]

    def count(table: str) -> int:
        return db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]

    return {
        "state": "observed",
        "works": count("work"),
        "editions": count("edition"),
        "authors": count("author"),
        "series": count("series"),
        "by_type": grouped("SELECT type, count(*) FROM work GROUP BY 1"),
        "by_format": grouped("SELECT format, count(*) FROM edition GROUP BY 1"),
        "with_isbn": db.execute(
            "SELECT count(DISTINCT work_id) FROM edition WHERE isbn13 IS NOT NULL"
        ).fetchone()[0],
        "with_synopsis": db.execute(
            "SELECT count(*) FROM work WHERE synopsis IS NOT NULL AND synopsis != ''"
        ).fetchone()[0],
    }


def _titles(db) -> dict[str, tuple[str, str | None]]:
    return {row[0]: (row[1], row[2]) for row in db.execute("SELECT id, title, type FROM work")}


def changes(db, info: dict, previous_db, previous_version: str) -> dict:
    """What this snapshot added, removed, merged and retitled against the previous one.

    A work that became an alias of another (two works merged) is a merge, not a removal.
    """
    now, before = _titles(db), _titles(previous_db)
    merged = {row[0] for row in db.execute("SELECT old_id FROM id_alias")}
    added = sorted((w for w in now if w not in before), key=lambda w: (now[w][0].casefold(), w))
    gone = sorted((w for w in before if w not in now), key=lambda w: (before[w][0].casefold(), w))
    removed = [w for w in gone if w not in merged]
    retitled = [w for w in sorted(now) if w in before and before[w][0] != now[w][0]]
    return {
        "state": "observed",
        "plates": added_plates(db, info, added),
        "plate_candidates": added,
        "from_version": previous_version,
        "to_version": info["version"],
        "added_count": len(added),
        "removed_count": len(removed),
        "merged_count": len(gone) - len(removed),
        "retitled_count": len(retitled),
        "added": [
            {
                "id": w,
                "title": now[w][0],
                "type": now[w][1],
                "cover": catalogue_covers.metadata(db, info, w),
            }
            for w in added[:SHOWN]
        ],
        "removed": [
            {"id": w, "title": before[w][0], "type": before[w][1]} for w in removed[:SHOWN]
        ],
        "retitled": [{"id": w, "from": before[w][0], "to": now[w][0]} for w in retitled[:SHOWN]],
    }


def harvest(db, since: str | None, since_version: str | None) -> dict:
    """Per-source harvest evidence recorded in the snapshot, never its query text.

    With a previous snapshot the window is everything recorded after that snapshot's newest
    harvest entry; otherwise it is everything the snapshot recorded.
    """
    present = tables(db)
    if not {"harvest_log", "source_record"} <= present:
        return unavailable("This snapshot carries no harvest evidence.")
    window = "AND fetched_at > :since" if since else ""
    rows = db.execute(
        "SELECT source, count(*) asked, sum(status='error') errors, max(fetched_at) last_at, "
        "(SELECT h.status FROM harvest_log h WHERE h.source=l.source "
        "ORDER BY h.fetched_at DESC, h.id DESC LIMIT 1) last_status "
        f"FROM harvest_log l WHERE 1 {window} GROUP BY source ORDER BY source LIMIT :limit",
        {"since": since, "limit": SOURCE_LIMIT + 1},
    ).fetchall()
    new = dict(
        db.execute(
            f"SELECT source, count(*) FROM source_record WHERE 1 {window} GROUP BY source",
            {"since": since},
        ).fetchall()
    )
    if len(rows) > SOURCE_LIMIT or any(
        not isinstance(value, str) or len(value) > 100
        for row in rows
        for value in (row["source"], row["last_at"], row["last_status"])
    ):
        raise catalogue.CatalogueError("Catalogue sources exceed the dashboard limit", 422)
    last = db.execute("SELECT max(fetched_at) FROM harvest_log").fetchone()[0]
    return {
        "state": "observed",
        "live": unavailable(NOT_LIVE),
        "last_recorded_at": last,
        "last_recorded_age_seconds": age_seconds(last),
        "window": {"since": since, "since_version": since_version},
        "sources": [
            {
                "source": row["source"],
                "asked": row["asked"],
                "new_records": new.get(row["source"], 0),
                "errors": row["errors"],
                "last_at": row["last_at"],
                "last_status": row["last_status"],
            }
            for row in rows
        ],
        "tripped": unavailable(NO_CYCLES),
        "budget_deferred": unavailable(NO_CYCLES),
    }


def covers(db) -> dict:
    """Cover downloads and the upscale queue as the snapshot recorded them."""
    present = tables(db)
    if not {"cover_asset", "work_cover"} <= present:
        return unavailable("This snapshot carries no cover records.")
    one = lambda sql: db.execute(sql).fetchone()[0]
    result = {
        "state": "observed",
        "saved": one("SELECT count(*) FROM cover_asset"),
        "works_with_covers": one(
            "SELECT count(*) FROM work_cover c WHERE EXISTS (SELECT 1 FROM work w WHERE w.id=c.work_id)"
        ),
        "awaiting": unavailable(NO_INBOX),
        "failed": unavailable(NO_INBOX),
        "last_download": unavailable(
            "BL Catalog records no download time in a snapshot; its cover files are not read here."
        ),
    }
    if not {"cover_upscale_job", "cover_derivative"} <= present:
        result["upscale"] = unavailable("This snapshot carries no upscale queue.")
        return result
    states = dict(
        db.execute(
            "SELECT CASE WHEN state='pending' AND attempts>0 THEN 'retry' ELSE state END, count(*) "
            "FROM cover_upscale_job GROUP BY 1"
        ).fetchall()
    )
    result["upscale"] = {
        "state": "observed",
        "upscaled": one("SELECT count(*) FROM cover_derivative"),
        "awaiting": states.get("pending", 0),
        "retry": states.get("retry", 0),
        "running": states.get("running", 0),
        "failed": states.get("failed", 0),
        "paused": unavailable(
            "BL Catalog's upscale pause switch is not reported to Librarium yet."
        ),
    }
    return result


def age_seconds(value: str | None) -> int | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0, round((datetime.now(UTC) - moment).total_seconds()))


def snapshot_report(db, info: dict, directory: Path) -> dict:
    key = (
        str(directory),
        info["version"],
        info["sha256"],
        settings.LIBRARIUM_CATALOGUE_COVER_DIR,
        settings.LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR,
    )
    if key in _cache:
        report = copy.deepcopy(_cache[key])
        refresh_artwork(db, info, report["changes"])
        return report
    older = [v for v in saved_versions(directory) if version_key(v) < version_key(info["version"])]
    since = None
    if not older:
        diff = unavailable(
            "No earlier snapshot is kept beside this one, so there is nothing to compare."
        )
    else:
        try:
            path = directory / f"{older[-1]}.sqlite"
            catalogue.validate(path, catalogue.identity(path), older[-1])
            with catalogue.connection(path, seconds=5) as old:
                if "harvest_log" in tables(old):
                    since = old.execute("SELECT max(fetched_at) FROM harvest_log").fetchone()[0]
                diff = changes(db, info, old, older[-1])
        except catalogue.CatalogueError, OSError, sqlite3.Error, ValueError:
            since = None
            diff = unavailable(f"The previous snapshot {older[-1]} could not be read.")
    report = {
        "harvester": harvest(db, since, older[-1] if since else None),
        "changes": diff,
        "size": size(db),
        "covers": covers(db),
    }
    if len(_cache) >= CACHE_LIMIT:
        _cache.pop(next(iter(_cache)))
    _cache[key] = copy.deepcopy(report)
    refresh_artwork(db, info, report["changes"])
    return report


def refresh_artwork(db, info: dict, diff: dict):
    if diff.get("state") == "observed":
        ids = diff.pop("plate_candidates", [w["id"] for w in diff["added"]])
        diff["plates"] = added_plates(db, info, ids)
        for row in diff["added"]:
            row["cover"] = catalogue_covers.metadata(db, info, row["id"])


def jobs(now: datetime) -> dict:
    """Librarium's own jobs: the operator sampler plus failures in the last day."""
    observed = operational_status.database_observations(now)["jobs"]
    if observed.get("state") != "observed":
        return unavailable("Librarium's job table could not be read.")
    try:
        failed = Job.objects.filter(state="failed", updated_at__gte=now - timedelta(days=1))
        latest = failed.order_by("-updated_at").values("kind", "updated_at").first()
        failures = failed.count()
    except DatabaseError:
        return unavailable("Librarium's job table could not be read.")
    return {
        "state": "observed",
        "queued": observed["states"]["queued"],
        "running": observed["states"]["running"],
        "expired_leases": observed["expired_running_leases"],
        "oldest_queued_age_seconds": observed["oldest_sampled_queued_age_seconds"],
        "sample_incomplete": observed["incomplete"],
        "failed_last_day": failures,
        "latest_failure": latest
        and {"kind": latest["kind"], "at": latest["updated_at"].isoformat()},
    }


def librarium(directory: Path | None, info: dict | None, now: datetime) -> dict:
    production = reference_production.status()
    outcome = production.get("last_outcome")
    sync = (
        {
            "state": "observed",
            "outcome": outcome["state"],
            "completed_at": outcome["completed_at"],
            "version": outcome["version"],
        }
        if outcome
        else unavailable(
            "Reference imports are not running inside Librarium yet."
            if production["status"] == "not_configured"
            else "No reference import has completed yet."
            if production["status"] == "manual"
            else "Librarium's reference import state could not be verified."
        )
    )
    snapshot: dict = unavailable("No catalogue snapshot is configured.")
    if directory is not None and info is not None:
        versions = saved_versions(directory)
        latest = versions[-1] if versions else info["version"]
        dated = date(*map(int, info["version"].split(".")[:3]))
        snapshot = {
            "state": "observed",
            "pinned": info,
            "dated": dated.isoformat(),
            "age_days": (now.date() - dated).days,
            "stale_after_days": STALE_DAYS,
            "stale": (now.date() - dated).days > STALE_DAYS,
            "latest_available": latest,
            "behind": version_key(latest) > version_key(info["version"]),
            "kept": versions[-SHOWN:][::-1],
        }
    return {
        "snapshot": snapshot,
        "last_sync": sync,
        "jobs": jobs(now),
        "catalogue_sync": catalogue_sync.saved(),
    }


def snapshot_headline(report: dict) -> dict:
    snapshot = report["librarium"]["snapshot"]
    if snapshot["state"] != "observed":
        return {
            "level": "unavailable",
            "reasons": [report["catalogue_reason"]],
        }
    reasons = []
    sync_state = report["librarium"]["catalogue_sync"]
    remote = report["telemetry"].get("status", {}).get("published_version") or sync_state.get(
        "published_version"
    )
    if (
        isinstance(remote, str)
        and catalogue.valid_version(remote)
        and version_key(remote) > version_key(snapshot["pinned"]["version"])
    ):
        created = (
            sync_state.get("published_created_at")
            if sync_state.get("published_version") == remote
            else None
        )
        published_age = age_seconds(created) if created else None
        age_note = (
            f" Published {published_age:,} seconds ago."
            if published_age is not None
            else " Publication time is not reported."
        )
        reasons.append(
            f"Librarium serves {snapshot['pinned']['version']} ({snapshot['age_days']:,} days old); BL Catalog has published {remote}."
            + age_note
        )
    if sync_state.get("state") == "failed":
        reasons.append(sync_state.get("failure", "Catalogue sync needs attention."))
    if sync_state.get("state") == "syncing" and sync_state.get("phase") == "staging":
        reasons.append(
            f"Snapshot {sync_state.get('version')} is waiting for its complete cover set: {sync_state.get('verified', 0):,} of {sync_state.get('total', 0):,} verified."
        )
    if sync_state.get("served_version") == snapshot["pinned"]["version"]:
        verified, total = sync_state.get("served_verified", 0), sync_state.get("served_total", 0)
        if verified < total:
            reasons.append(
                f"Local catalogue covers are incomplete: {verified:,} of {total:,} verified."
            )
    elif not settings.LIBRARIUM_CATALOGUE_FIXTURE:
        reasons.append(
            "Local catalogue cover completeness has not been verified by the sync worker."
        )
    if snapshot["stale"]:
        reasons.append(
            f"The served snapshot is {snapshot['age_days']:,} days old; snapshots older than "
            f"{snapshot['stale_after_days']} days need attention."
        )
    if snapshot["behind"]:
        reasons.append(
            f"A newer snapshot ({snapshot['latest_available']}) is saved but Librarium still "
            f"serves {snapshot['pinned']['version']}."
        )
    harvester = report["harvester"]
    # Without a previous kept snapshot the window is all recorded history, so old errors
    # are shown but cannot hold the headline at attention forever.
    windowed = harvester.get("state") == "observed" and harvester["window"]["since"]
    errors = sum(s["errors"] for s in harvester["sources"]) if windowed else 0
    if errors:
        reasons.append(f"{errors:,} harvest requests recorded errors in this snapshot's window.")
    upscale = report["covers"].get("upscale", {})
    if upscale.get("failed"):
        reasons.append(f"{upscale['failed']:,} cover upscales failed.")
    sync = report["librarium"]["last_sync"]
    if sync["state"] == "observed" and sync["outcome"] == "failed":
        reasons.append("The last reference import failed.")
    jobs_seen = report["librarium"]["jobs"]
    if jobs_seen["state"] != "observed":
        reasons.append(jobs_seen["reason"])
    else:
        if jobs_seen["expired_leases"]:
            reasons.append(f"{jobs_seen['expired_leases']:,} running jobs are past their lease.")
        if jobs_seen["failed_last_day"]:
            reasons.append(f"{jobs_seen['failed_last_day']:,} jobs failed in the last day.")
    if reasons:
        return {"level": "attention", "reasons": reasons}
    return {
        "level": "healthy",
        "reasons": [
            (
                f"Librarium serves the newest saved snapshot, {snapshot['pinned']['version']}, "
                "and nothing in its saved evidence needs attention."
            )
        ],
    }


def added_plates(db, info: dict, work_ids: list[str]) -> list[dict]:
    plates, seen = [], set()
    for work_id in work_ids[:300]:
        work = db.execute("SELECT title FROM work WHERE id=?", (work_id,)).fetchone()
        if not work:
            continue
        art, collected = catalogue_covers.metadata(db, info, work_id), None
        if "work_contains" in tables(db):
            parents = db.execute(
                "SELECT w.id, w.title FROM work_contains c JOIN work w ON w.id=c.parent_id "
                "WHERE c.child_id=? ORDER BY w.title, w.id LIMIT 32",
                (work_id,),
            )
            for parent in parents:
                candidate = catalogue_covers.metadata(db, info, parent["id"])
                if candidate and (art is None or candidate["sha256"] == art["sha256"]):
                    art, collected = candidate, parent["title"]
                    break
        if art and art["sha256"] not in seen:
            seen.add(art["sha256"])
            plates.append(
                {"id": work_id, "title": work["title"], "cover": art, "collected_in": collected}
            )
            if len(plates) == 8:
                break
    return plates


def upscaled_examples(db, info: dict) -> list[dict]:
    if not settings.LIBRARIUM_CATALOGUE_UPSCALED_COVER_DIR:
        return []
    try:
        rows = db.execute(
            "SELECT w.id, w.title FROM work w JOIN work_cover c ON c.work_id=w.id "
            "JOIN cover_derivative d ON d.original_sha256=c.sha256 "
            "ORDER BY d.created_at DESC, w.id LIMIT 100"
        )
        result, seen = [], set()
        for row in rows:
            art = catalogue_covers.metadata(db, info, row["id"], upscaled=True)
            if art and art["sha256"] not in seen:
                result.append({"id": row["id"], "title": row["title"], "cover": art})
                seen.add(art["sha256"])
                if len(result) == 3:
                    break
        return result
    except sqlite3.OperationalError:
        return []


def status_page_url() -> str:
    value = settings.LIBRARIUM_CATALOGUE_STATUS_PAGE_URL
    if not value:
        return ""
    try:
        return catalogue_status.base_url(value)
    except ValueError:
        return ""


def headline(report: dict) -> dict:
    telemetry = report["telemetry"]
    if telemetry["state"] == "unavailable":
        return {"level": "unavailable", "reasons": [telemetry["reason"]]}
    if telemetry["state"] == "stale":
        return {"level": "stale", "reasons": ["BL Catalog status is more than five minutes old."]}
    live = telemetry["status"]["live"]
    if live["state"] == "unknown":
        return {"level": "unavailable", "reasons": ["The harvester has not reported its state."]}
    reasons = []
    cycles = telemetry["status"].get("cycles", [])
    latest = cycles[0] if cycles else {}
    if latest.get("tripped"):
        reasons.append("Some sources need attention; the latest cycle ran with a tripped source.")
    if any(s.get("status") == "error" for s in latest.get("stages", {}).values()):
        reasons.append("A stage failed in the latest cycle.")
    if live.get("paused"):
        reasons.append("The harvester is paused.")
    elif live.get("stalled"):
        return {"level": "stalled", "reasons": ["The harvester has stopped reporting progress."]}
    if live["state"] == "stopped":
        reasons.append("The harvester is stopped.")
    if telemetry.get("failure"):
        reasons.append("The latest status poll failed; showing the last good report.")
    if telemetry.get("covers", {}).get("upscale", {}).get("failed"):
        reasons.append("Some cover upscales failed.")
    if report["saved_headline"]["level"] != "healthy":
        reasons.extend(report["saved_headline"]["reasons"])
    return {"level": "attention" if reasons else "healthy", "reasons": reasons}


def build(now: datetime | None = None) -> dict:
    now = now or timezone.now()
    report: dict = {
        "checked_at": now.isoformat(timespec="seconds"),
        "telemetry": catalogue_status.saved(now),
        "status_page_url": status_page_url(),
        "lately": unavailable("No added works can be verified against the served snapshot."),
        "upscaled_examples": [],
        "controls": unavailable(NO_CONTROLS),
        "cycles": unavailable(NO_CYCLES),
        "clients": [
            {"id": key, "name": name, **unavailable(NOT_REPORTED)} for key, name in CLIENTS
        ],
    }
    directory = info = None
    reason = "No catalogue snapshot is configured. Library browsing remains available."
    sections: dict = dict.fromkeys(("harvester", "changes", "size", "covers"))
    if settings.LIBRARIUM_CATALOGUE_DIR:
        try:
            with catalogue.snapshot(
                settings.LIBRARIUM_CATALOGUE_DIR,
                fixture=settings.LIBRARIUM_CATALOGUE_FIXTURE,
                seconds=5,
            ) as (db, info):
                directory = Path(settings.LIBRARIUM_CATALOGUE_DIR).resolve(strict=True)
                sections = copy.deepcopy(snapshot_report(db, info, directory))
                telemetry = report["telemetry"]
                remote = telemetry.get("status", {}).get("snapshot")
                if (
                    remote
                    and remote.get("version") == info["version"]
                    and not remote.get("changes", {}).get("first")
                ):
                    added = remote.get("changes", {}).get("added", [])
                    report["lately"] = {
                        "state": "observed",
                        "count": remote.get("changes", {}).get("added_count", len(added)),
                        "plates": added_plates(db, info, [w["id"] for w in added if "id" in w]),
                    }
                elif sections["changes"]["state"] == "observed":
                    report["lately"] = {
                        "state": "observed",
                        "count": sections["changes"]["added_count"],
                        "plates": sections["changes"]["plates"],
                    }
                report["upscaled_examples"] = upscaled_examples(db, info)
        except catalogue.CatalogueError as error:
            directory = info = None
            reason = f"The catalogue snapshot could not be read: {error}"
    for name, value in sections.items():
        report[name] = value if value is not None else unavailable(reason)
    report["catalogue_reason"] = reason
    report["librarium"] = librarium(directory, info, now)
    report["saved_headline"] = snapshot_headline(report)
    report["headline"] = headline(report)
    del report["catalogue_reason"]
    return report


@require_GET
def health(request):
    if request.GET:
        return response({"error": "The health report takes no parameters"}, 400)
    return response(build())
