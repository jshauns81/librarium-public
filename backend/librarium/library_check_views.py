import json
import math

from django.views.decorators.http import require_http_methods

from librarium import library_check_jobs
from librarium.views import job_data, response

MAX_BODY_BYTES = 4096


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def check(request, kind, source_id=None):
    try:
        if request.method == "GET":
            if any(len(request.GET.getlist(name)) != 1 for name in request.GET):
                raise ValueError
            if set(request.GET) == {"page"}:
                return history(kind, request.GET["page"], source_id)
            if set(request.GET) != {"request_key"}:
                raise ValueError
            key = library_check_jobs.request_uuid(request.GET["request_key"])
            job = library_check_jobs.recover(kind, key, source_id)
            if job is None:
                return response({"error": "This check request is not recorded yet"}, 404)
            return response(job_data(job))
        if request.GET:
            raise ValueError
        if request.content_type != "application/json":
            return response({"error": "Check requests require JSON"}, 415)
        length = request.META.get("CONTENT_LENGTH", "")
        if length and (not length.isascii() or not length.isdecimal()):
            raise ValueError
        significant = length.lstrip("0") or "0"
        if len(significant) > 4 or int(significant) > MAX_BODY_BYTES:
            return response({"error": "Check requests are limited to 4096 bytes"}, 413)
        body = request.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            return response({"error": "Check requests are limited to 4096 bytes"}, 413)
        value = json.loads(body, object_pairs_hook=unique_object)
        return response(
            job_data(
                library_check_jobs.enqueue(
                    kind, value, request.headers.get("Idempotency-Key", ""), source_id=source_id
                )
            ),
            202,
        )
    except library_check_jobs.CheckError as error:
        return response({"error": str(error)}, error.status)
    except ValueError, TypeError, UnicodeError:
        return response({"error": "Choose exact pinned inputs and one UUID request key"}, 400)


def history(kind, text, source_id):
    if not 1 <= len(text) <= 5 or not text.isascii() or not text.isdecimal():
        raise ValueError
    page = int(text)
    if not 1 <= page <= 10000:
        raise ValueError
    rows, total, fields = library_check_jobs.history(kind, page, source_id)
    return response(
        {
            "jobs": [
                {
                    **job_data(row, result=False),
                    "result_summary": {name: getattr(row, f"summary_{name}") for name in fields},
                }
                for row in rows
            ],
            "page": page,
            "page_size": library_check_jobs.HISTORY_PAGE_SIZE,
            "total": total,
            "pages": max(1, math.ceil(total / library_check_jobs.HISTORY_PAGE_SIZE)),
        }
    )


@require_http_methods(["GET", "POST"])
def reconciliations(request):
    return check(request, "library_reconcile")


@require_http_methods(["GET", "POST"])
def assessments(request, source_id):
    return check(request, "book_assessment", source_id)
