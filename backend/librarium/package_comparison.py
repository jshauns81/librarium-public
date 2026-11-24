"""Compare a preserved report with an explicitly chosen, pinned catalogue work."""

import unicodedata

from django.conf import settings
from django.views.decorators.http import require_GET

from librarium import artifacts, catalogue, file_inspections, package_identifiers
from librarium.identifier_evidence import validate_identifier_evidence
from librarium.models import Job
from librarium.validation import bounded_text
from librarium.views import response

POLICY_VERSION = "librarium.package-metadata.v3"
MAX_NAMES = 64
MAX_TEXT = 512
SCOPE = (
    "Package metadata agreement only. Creator roles and title refinements were not retained "
    "by this inspection. Matching names or recorded aliases do not identify the work, "
    "establish ownership, prove content completeness or authorize library changes. "
    "No file or catalogue metadata was changed."
)
UNKNOWN_NAMES = {"unknown", "unknown author", "various", "various authors", "anonymous"}


def normalized(value: str) -> str:
    return unicodedata.normalize("NFC", " ".join(value.split()).casefold())


def metadata_values(report: dict, name: str) -> list[str]:
    entries = report.get("metadata", [])
    if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
        raise file_inspections.InspectionError("The report's package metadata is unavailable")
    values = [e.get("text") for e in entries if e.get("name") == name]
    if len(values) > MAX_NAMES or any(
        not isinstance(value, str) or not bounded_text(value, MAX_TEXT) for value in values
    ):
        raise file_inspections.InspectionError(
            "Package metadata exceeds the comparison limit; no agreement was recorded", 422
        )
    return values


def selected_work(db, work_id: str) -> dict:
    row = db.execute(
        "SELECT id,substr(title,1,513) AS title FROM work WHERE id=?", (work_id,)
    ).fetchone()
    if row is None:
        raise catalogue.CatalogueError("Catalogue work not found", 404)
    authors = [
        {"id": str(a["id"]), "name": a["name"]}
        for a in db.execute(
            "SELECT a.id,substr(a.name,1,513) AS name FROM author a "
            "JOIN work_author wa ON wa.author_id=a.id "
            "WHERE wa.work_id=? AND wa.role='author' ORDER BY a.id LIMIT 65",
            (work_id,),
        )
    ]
    if len(authors) > MAX_NAMES or any(
        not isinstance(value, str) or not bounded_text(value, MAX_TEXT)
        for value in [row["title"], *(a["name"] for a in authors)]
    ):
        raise catalogue.CatalogueError(
            "Catalogue credits exceed the comparison limit; no agreement was recorded", 422
        )
    return {"work_id": row["id"], "title": row["title"], "authors": authors}


def name_owners(db, names: list[str], *, normalize=normalized) -> dict:
    columns = {row["name"] for row in db.execute("PRAGMA table_info(author_alias)")}
    if not {"author_id", "name"} <= columns:
        raise catalogue.CatalogueError("This snapshot has no compatible author-alias evidence")
    oversized = db.execute(
        "SELECT 1 FROM author WHERE typeof(name)!='text' OR length(name)>512 "
        "UNION ALL SELECT 1 FROM author_alias WHERE typeof(name)!='text' OR length(name)>512 "
        "LIMIT 1"
    ).fetchone()
    if oversized:
        raise catalogue.CatalogueError(
            "Catalogue name evidence exceeds the comparison limit; no agreement was recorded", 422
        )
    keys = sorted({normalized(name) for name in names if normalized(name)})
    if not keys:
        return {}
    db.create_function("comparison_name", 1, normalize, deterministic=True)
    placeholders = ",".join("?" for _ in keys)
    # Check every author, including credits outside the chosen work, for collisions.
    rows = db.execute(
        "SELECT spelling,min(author_id) AS author_id,count(DISTINCT author_id) AS owners "
        "FROM (SELECT id AS author_id,comparison_name(name) AS spelling FROM author "
        "UNION ALL SELECT aa.author_id,comparison_name(aa.name) FROM author_alias aa "
        "JOIN author a ON a.id=aa.author_id) "
        f"WHERE spelling IN ({placeholders}) GROUP BY spelling",
        keys,
    )
    return {row["spelling"]: (str(row["author_id"]), row["owners"]) for row in rows}


def creator_finding(names: list[str], authors: list[dict], owners: dict, complete: bool) -> dict:
    selected = {a["id"]: a["name"] for a in authors}
    matches = []
    covered = set()
    ambiguous = False
    for name in names:
        key = normalized(name)
        author_id, count = owners.get(key, (None, 0))
        state = "different"
        canonical = None
        basis = None
        if count > 1:
            state = "ambiguous"
            author_id = None
        elif author_id in selected and key not in UNKNOWN_NAMES and key:
            canonical = selected[author_id]
            basis = "canonical" if key == normalized(canonical) else "alias"
            state = "same"
            if author_id in covered:
                ambiguous = True
            covered.add(author_id)
        else:
            author_id = None
        matches.append(
            {
                "epub_name": name,
                "author_id": author_id,
                "catalogue_name": canonical,
                "basis": basis,
                "status": state,
            }
        )
    missing = [a for a in authors if a["id"] not in covered]
    if (
        not complete
        or not names
        or not authors
        or any(not normalized(n) or normalized(n) in UNKNOWN_NAMES for n in names)
        or any(not normalized(a["name"]) or normalized(a["name"]) in UNKNOWN_NAMES for a in authors)
    ):
        state = "unknown"
    elif ambiguous or any(m["status"] == "ambiguous" for m in matches):
        state = "ambiguous"
    elif len(covered) == len(authors) and all(m["status"] == "same" for m in matches):
        state = "same"
    else:
        state = "partial" if covered else "different"
    return {
        "status": state,
        "epub": names,
        "catalogue": authors,
        "matches": matches if complete else [],
        "missing_authors": missing if complete else [],
    }


def compare(envelope: dict, db, info: dict, work_id: str) -> dict:
    from librarium.attribution_comparison import compare as compare_attribution

    report = envelope["report"]
    work = selected_work(db, work_id)
    titles = metadata_values(report, "title")
    names = metadata_values(report, "creator")
    complete = report["inspection_complete"]
    distinct_titles = {normalized(t) for t in titles}
    if (
        not complete
        or not distinct_titles
        or "" in distinct_titles
        or not normalized(work["title"])
    ):
        title_state = "unknown"
    elif len(distinct_titles) > 1:
        title_state = "ambiguous"
    else:
        title_state = "same" if distinct_titles == {normalized(work["title"])} else "different"
    creators = creator_finding(names, work["authors"], name_owners(db, names), complete)
    try:
        identifiers = validate_identifier_evidence(report)
    except ValueError:
        raise file_inspections.InspectionError(
            "Identifier declaration capture is unavailable"
        ) from None
    return {
        "schema_version": "librarium.package-comparison.v3",
        "policy_version": POLICY_VERSION,
        "job_id": envelope["job_id"],
        "source_sha256": envelope["source_sha256"],
        "report_sha256": envelope["report_sha256"],
        "catalogue": {**work, **info},
        "title": {"status": title_state, "epub": titles, "catalogue": work["title"]},
        "creators": creators,
        "isbn": package_identifiers.compare_isbns(
            metadata_values(report, "identifier"), db, work_id, complete, evidence=identifiers
        ),
        "metadata_agrees": title_state == creators["status"] == "same",
        "source_attribution": compare_attribution(envelope, db, info, work_id),
        "inspection_complete": complete,
        "ready": False,
        "scope": SCOPE,
    }


def comparison_parameters(params):
    required = {"work", "version", "sha256", "source_sha256", "report_sha256"}
    if (
        set(params) != required
        or any(len(params.getlist(key)) != 1 or not params[key] for key in params)
        or not bounded_text(params["work"], 80)
        or any(
            not catalogue.DIGEST.fullmatch(params[key]) for key in required - {"work", "version"}
        )
        or not catalogue.valid_version(params["version"])
    ):
        raise file_inspections.InspectionError(
            "Choose an inspection report and a pinned catalogue work", 400
        )


def compared_report(job_id, params):
    job = Job.objects.get(pk=job_id)
    if (
        job.target_id != params["source_sha256"]
        or job.result.get("report_sha256") != params["report_sha256"]
    ):
        raise file_inspections.InspectionError("The selected inspection source or report changed")
    envelope = file_inspections.report(job)
    with catalogue.snapshot(
        settings.LIBRARIUM_CATALOGUE_DIR,
        params["version"],
        params["sha256"],
        settings.LIBRARIUM_CATALOGUE_FIXTURE,
    ) as (db, info):
        data = compare(envelope, db, info, params["work"])
    return job, envelope, data


@require_GET
def comparison(request, job_id):
    try:
        comparison_parameters(request.GET)
        _, _, data = compared_report(job_id, request.GET)
        return response(data)
    except Job.DoesNotExist:
        return response({"error": "EPUB inspection not found"}, 404)
    except (
        file_inspections.InspectionError,
        artifacts.ArtifactError,
        catalogue.CatalogueError,
    ) as error:
        return response({"error": str(error)}, error.status)
