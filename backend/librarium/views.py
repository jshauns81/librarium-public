import json
import re
import unicodedata
import uuid
from urllib.parse import unquote_to_bytes

from django.conf import settings
from django.db import DatabaseError, IntegrityError, connection
from django.db.models import Q
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from librarium import retired_jobs
from librarium.catalogue import CatalogueError
from librarium.models import Job, Work
from librarium.operator_identity import principal
from librarium.services import cancel, enqueue, enqueue_catalogue
from librarium.validation import bounded_text


def response(value: dict, status: int = 200) -> JsonResponse:
    result = JsonResponse(value, status=status)
    result["Cache-Control"] = "no-store"
    return result


def csrf_failure(request, reason=""):
    return response({"error": "CSRF verification failed", "code": "csrf_failed"}, 403)


class NoStoreMiddleware:
    """Job responses and every cancellation are never cached."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        result = self.get_response(request)
        if request.path.startswith("/api/jobs") or request.path.endswith("/cancel"):
            result["Cache-Control"] = "no-store"
        return result


@require_http_methods(["GET"])
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return response({"status": "unavailable"}, 503)
    return response({"status": "ready"})


def _check_projection(job: Job) -> dict:
    """Captured check intent; absent historical fields stay explicitly null."""
    intent = job.input.get("intent")
    intent = intent if isinstance(intent, dict) else {}
    values = {
        "catalogue_version": intent.get("version"),
        "catalogue_sha256": intent.get("sha256"),
    }
    if job.kind == "book_assessment":
        values |= {
            "source_job_id": intent.get("source_job_id"),
            "source_report_sha256": intent.get("report_sha256"),
            "catalogue_work_id": intent.get("catalogue_work_id"),
            "reconciliation_key": intent.get("reconciliation"),
            "reference": intent.get("reference"),
        }
    return values


def retired_job_data(job: Job) -> dict:
    """A stored record of work Librarium no longer runs, read as finished history.

    Nothing of the stored input or result is returned except the title and the input
    fingerprint: no report, receipt, locator or operator identity. Retired work that was
    left queued or running reads as cancelled, so nothing polls it or counts it as active;
    `stored_state` keeps what the database holds.
    """
    title = job.input.get("title") if isinstance(job.input, dict) else None
    unfinished = job.state in retired_jobs.OPEN_STATES
    return {
        "id": str(job.pk),
        "request_key": str(job.request_key),
        "work_id": job.target_id or job.work_id,
        "kind": job.kind,
        "retired": True,
        "title": title if isinstance(title, str) else "",
        "state": "cancelled" if unfinished else job.state,
        "stored_state": job.state,
        "revision": job.revision,
        "checkpoint": job.checkpoint,
        "attempts": job.attempts,
        "message": retired_jobs.UNFINISHED_MESSAGE if unfinished else job.message,
        "result": {},
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "source_version": "",
        "source_sha256": None,
        "input_fingerprint": job.input_fingerprint,
    }


def job_data(job: Job, *, result: bool = True) -> dict:
    from librarium.book_workspace import WorkspaceError, recorded_origin

    if job.kind in retired_jobs.RETIRED_KINDS:
        return retired_job_data(job)

    origin = None
    if job.kind == "epub":
        try:
            origin = recorded_origin(job)
        except WorkspaceError:
            pass
    return {
        **({"library_origin": origin} if origin is not None else {}),
        "id": str(job.pk),
        "request_key": str(job.request_key),
        "work_id": job.target_id or job.work_id,
        "kind": job.kind,
        "title": job.input["title"],
        "state": job.state,
        "revision": job.revision,
        "checkpoint": job.checkpoint,
        "attempts": job.attempts,
        "message": job.message,
        **({"result": job.result} if result else {}),
        "updated_at": job.updated_at.isoformat(),
        "source_version": job.input["source_version"],
        "source_sha256": job.input.get("source_sha256"),
        "input_fingerprint": job.input_fingerprint,
        **(
            {
                key: job.input.get(key)
                for key in (
                    "source_job_id",
                    "source_report_sha256",
                    "source_size",
                    "policy",
                    "validator",
                )
            }
            if job.kind == "epub_validation"
            else {}
        ),
        **(_check_projection(job) if job.kind in {"library_reconcile", "book_assessment"} else {}),
    }


@ensure_csrf_cookie
@require_http_methods(["GET"])
def session(request):
    from librarium import epub_validations

    return response(
        {
            "csrf": get_token(request),
            "synthetic": True,
            "library": bool(settings.DIRECT_LIBRARY_ROOT or settings.LIBRARIUM_LIBRARY_URL),
            "direct_library": bool(settings.DIRECT_LIBRARY_ROOT),
            "file_inspections": bool(settings.LIBRARIUM_ARTIFACT_DIR),
            "file_inspection_max_bytes": 32 * 1024 * 1024,
            "epub_validation": epub_validations.configured(),
            "epub_validator": epub_validations.description(),
        }
    )


@require_http_methods(["GET"])
def works(request):
    query = request.GET.get("q", "")
    series = request.GET.get("series", "")
    try:
        page = int(request.GET.get("page", "1"))
        if not 1 <= page <= 10000 or not bounded_text(query, 200) or not bounded_text(series, 160):
            raise ValueError
    except ValueError:
        return response({"error": "Use a valid page and a search of up to 200 characters"}, 400)
    query = query.strip()
    values = Work.objects.filter(
        Q(title__icontains=query) | Q(author__icontains=query) | Q(series__icontains=query)
    )
    if series:
        values = values.filter(series=series)
    total = values.count()
    rows = values.order_by("id")[(page - 1) * 24 : page * 24]
    return response(
        {
            "works": [
                {
                    "id": row.pk,
                    "title": row.title,
                    "author": row.author,
                    "series": row.series,
                    "edition_count": len(row.payload["editions"]),
                    "source_version": row.payload["source_version"],
                }
                for row in rows
            ],
            "total": total,
            "page": page,
            "page_size": 24,
            "synthetic": True,
            "source_versions": sorted({row.payload["source_version"] for row in rows}),
        }
    )


@require_http_methods(["GET"])
def work(request, work_id):
    if not bounded_text(work_id, 40):
        return response(
            {"error": "Use a work identifier of up to 40 characters without controls"}, 400
        )
    try:
        return response(Work.objects.get(pk=work_id).payload)
    except Work.DoesNotExist:
        return response({"error": "Work not found"}, 404)


JOB_FILTERS = {"work_id", "kind"}
# Retired kinds stay filterable so stored history remains reachable.
JOB_KINDS = {
    "",
    "synthetic",
    "catalogue",
    "epub",
    "epub_validation",
    "library_reconcile",
    "book_assessment",
    retired_jobs.FILTER,
} | retired_jobs.RETIRED_KINDS
HISTORY_FILTERS = {"q", "state", "kind", "page"}
HISTORY_STATES = {"", "active", "queued", "running", "succeeded", "failed", "cancelled"}


def by_kind(records, kind):
    if kind == retired_jobs.FILTER:
        return records.filter(kind__in=retired_jobs.RETIRED_KINDS)
    return records.filter(kind=kind) if kind else records


@require_http_methods(["GET"])
def job_history(request):
    query = request.GET.get("q", "")
    state = request.GET.get("state", "")
    kind = request.GET.get("kind", "")
    page_text = request.GET.get("page", "1")
    if (
        set(request.GET) - HISTORY_FILTERS
        or any(len(request.GET.getlist(name)) != 1 for name in request.GET)
        or not bounded_text(query, 200)
        or state not in HISTORY_STATES
        or kind not in JOB_KINDS
        or not 1 <= len(page_text) <= 5
        or not page_text.isascii()
        or not page_text.isdecimal()
        or not 1 <= int(page_text) <= 10000
    ):
        return response(
            {
                "error": "Use a search of up to 200 characters, a supported job state and kind, "
                "and a page from 1 to 10000; each filter may appear once"
            },
            400,
        )
    page = int(page_text)
    records = by_kind(Job.objects.all(), kind)
    if state == "active":
        records = records.filter(state__in=["queued", "running"]).exclude(
            kind__in=retired_jobs.RETIRED_KINDS
        )
    elif state in {"queued", "running"}:
        records = records.filter(state=state).exclude(kind__in=retired_jobs.RETIRED_KINDS)
    elif state == "cancelled":
        # Retired work left unfinished reads as cancelled; see retired_job_data.
        records = records.filter(
            Q(state="cancelled")
            | Q(kind__in=retired_jobs.RETIRED_KINDS, state__in=retired_jobs.OPEN_STATES)
        )
    elif state:
        records = records.filter(state=state)
    if query.strip():
        records = records.filter(input__title__icontains=query.strip())
    total = records.count()
    rows = records.order_by("-created_at", "-id")[(page - 1) * 24 : page * 24]
    return response(
        {"jobs": [job_data(row) for row in rows], "total": total, "page": page, "page_size": 24}
    )


@require_http_methods(["GET", "POST"])
def jobs(request):
    if request.method == "GET":
        work_id = request.GET.get("work_id", "")
        kind = request.GET.get("kind", "")
        if (
            set(request.GET) - JOB_FILTERS
            or any(len(request.GET.getlist(name)) != 1 for name in request.GET)
            or kind not in JOB_KINDS
            or not bounded_text(work_id, 80)
        ):
            return response(
                {
                    "error": "Use one supported job kind and one work identifier "
                    "of up to 80 characters without controls"
                },
                400,
            )
        records = by_kind(Job.objects.all(), kind)
        # Unfinished retired work is history, never active work.
        running = Q(state__in=retired_jobs.OPEN_STATES) & ~Q(kind__in=retired_jobs.RETIRED_KINDS)
        active = list(records.filter(running).order_by("-created_at"))
        recent = list(records.exclude(running).order_by("-created_at")[:30])
        # Legacy synthetic rows may have a blank target, so a selection also matches work_id.
        selected = (
            records.filter(Q(target_id=work_id) | Q(work_id=work_id))
            .order_by("-created_at")
            .first()
            if work_id
            else None
        )
        values = {j.pk: j for j in active + recent}
        if selected:
            values[selected.pk] = selected
        return response({"jobs": [job_data(j) for j in values.values()]})
    try:
        body = json.loads(request.body)
        if isinstance(body, dict) and "catalogue_work_id" in body:
            # The review validates its exact field set, so mixed synthetic fields are refused.
            key = request.headers.get("Idempotency-Key", "")
            try:
                return response(job_data(enqueue_catalogue(body, key)), 202)
            except CatalogueError as error:
                return response({"error": str(error)}, error.status)
        if (
            not isinstance(body, dict)
            or set(body) != {"work_id"}
            or not isinstance(body["work_id"], str)
            or not bounded_text(body["work_id"], 40)
        ):
            raise ValueError("Choose one work")
        key = request.headers.get("Idempotency-Key", "")
        uuid.UUID(key)
        result = enqueue(body["work_id"], key)
        return response(job_data(result), 202)
    except Work.DoesNotExist:
        return response({"error": "Work not found"}, 404)
    except (ValueError, TypeError) as error:
        return response({"error": str(error) or "Use a valid request key"}, 400)
    except IntegrityError:
        return response({"error": "An inspection is already recorded; refresh its progress"}, 409)


@require_http_methods(["GET", "POST"])
def job(request, job_id):
    if request.GET:
        return response({"error": "Job detail and cancellation take no query parameters"}, 400)
    if request.method == "POST" and request.body not in {b"", b"{}"}:
        return response({"error": "Cancellation takes no parameters"}, 400)
    try:
        result = Job.objects.get(pk=job_id)
        if request.method == "POST":
            result = cancel(job_id)
        return response(job_data(result))
    except Job.DoesNotExist:
        return response({"error": "Inspection not found"}, 404)


@require_http_methods(["POST"])
def cancel_retired_job(request, job_id):
    """Cancel retired work left queued or running; nothing is continued or undone."""
    if not principal(request):
        return response({"error": "Authenticate an operator", "code": "reviewer_required"}, 401)
    if request.GET or request.body != b"{}" or request.content_type != "application/json":
        return response(
            {"error": "Cancellation takes exactly an empty JSON object", "code": "invalid_request"},
            400,
        )
    try:
        Job.objects.get(pk=job_id, kind__in=retired_jobs.RETIRED_KINDS)
    except Job.DoesNotExist:
        return response({"error": "Job not found", "code": "not_found"}, 404)
    return response({"job": job_data(cancel(job_id))})


@require_http_methods(["GET", "POST"])
def epub_inspections(request):
    from librarium import artifacts, file_inspections

    if request.method == "GET":
        if set(request.GET) != {"request_key"} or len(request.GET.getlist("request_key")) != 1:
            return response({"error": "Use exactly one request_key UUID"}, 400)
        try:
            key_text = request.GET["request_key"]
            if not 1 <= len(key_text) <= 45:
                raise ValueError
            key = uuid.UUID(key_text)
        except ValueError, AttributeError:
            return response({"error": "Use a valid request key"}, 400)
        existing = Job.objects.filter(request_key=key).first()
        if existing is None:
            return response({"error": "This request is not recorded yet"}, 404)
        if existing.kind != "epub":
            return response({"error": "This request key belongs to a different job kind"}, 409)
        return response(job_data(existing))
    if request.content_type != "application/epub+zip":
        return response({"error": "Upload a raw application/epub+zip body"}, 415)
    try:
        if request.GET:
            raise ValueError
        key_text = request.headers.get("Idempotency-Key", "")
        if not 1 <= len(key_text) <= 45:
            raise ValueError
        key = uuid.UUID(key_text)
        digest = request.headers.get("X-Source-SHA256", "")
        if not artifacts.DIGEST.fullmatch(digest):
            raise ValueError
        encoded = request.headers.get("X-Source-Name", "Uploaded%20EPUB.epub")
        if len(encoded) > 2880 or re.search(r"%(?![a-fA-F0-9]{2})", encoded):
            raise ValueError
        name = unquote_to_bytes(encoded).decode("utf-8", errors="strict")
        if (
            not name.strip()
            or len(name) > 240
            or any(char in name for char in "/\\")
            or any(unicodedata.category(char).startswith("C") for char in name)
        ):
            raise ValueError
        length = request.META.get("CONTENT_LENGTH", "")
        if length and (not length.isascii() or not length.isdecimal()):
            raise ValueError
        significant_length = length.lstrip("0") or "0"
        expected_size = (
            file_inspections.MAX_SOURCE_BYTES + 1
            if len(significant_length) > len(str(file_inspections.MAX_SOURCE_BYTES))
            else int(significant_length)
            if length
            else None
        )
    except ValueError, UnicodeError:
        return response(
            {
                "error": "Use a UUID request key, lowercase SHA-256 and a valid encoded filename and length"
            },
            400,
        )
    if expected_size is not None and expected_size > file_inspections.MAX_SOURCE_BYTES:
        return response({"error": "The EPUB exceeds the 32 MiB upload limit"}, 413)
    try:
        return response(
            job_data(file_inspections.enqueue(request, key, digest, name, expected_size)), 202
        )
    except (file_inspections.InspectionError, artifacts.ArtifactError) as error:
        return response({"error": str(error)}, error.status)


@require_http_methods(["GET"])
def epub_inspection_report(request, job_id):
    from librarium import artifacts, file_inspections

    if request.GET:
        return response({"error": "Report retrieval takes no parameters"}, 400)
    try:
        return response(file_inspections.report(Job.objects.get(pk=job_id)))
    except Job.DoesNotExist:
        return response({"error": "EPUB inspection not found"}, 404)
    except (file_inspections.InspectionError, artifacts.ArtifactError) as error:
        return response({"error": str(error)}, error.status)


@require_http_methods(["GET"])
def library(request):
    from librarium.library import LibraryError, browse

    try:
        return response(browse(request.GET))
    except LibraryError as error:
        return response(error.payload(), error.status)


@require_http_methods(["GET"])
def library_shelves(request):
    from librarium import library as reader
    from librarium import library_shelves

    try:
        return response(library_shelves.shelves(request.GET))
    except reader.LibraryError as error:
        return response(error.payload(), error.status)


@require_http_methods(["GET"])
def library_series(request):
    from librarium import library as reader
    from librarium import library_evidence

    try:
        return response(library_evidence.series(request.GET))
    except reader.LibraryError as error:
        return response(error.payload(), error.status)


@require_http_methods(["GET"])
def library_work(request, work_id: str):
    from librarium import library as reader
    from librarium import library_evidence

    try:
        return response(library_evidence.work(request.GET, work_id))
    except reader.LibraryError as error:
        return response(error.payload(), error.status)
