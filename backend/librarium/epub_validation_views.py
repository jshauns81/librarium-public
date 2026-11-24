import json
import uuid

from django.views.decorators.http import require_http_methods

from librarium import artifacts, epub_validations, file_inspections
from librarium.models import Job
from librarium.views import job_data, response

ERRORS = (
    epub_validations.ValidationError,
    file_inspections.InspectionError,
    artifacts.ArtifactError,
)


def _key(text):
    if not 1 <= len(text) <= 45:
        raise ValueError
    return uuid.UUID(text)


@require_http_methods(["GET", "POST"])
def validations(request, source_id):
    try:
        if request.method == "GET":
            if any(len(request.GET.getlist(name)) != 1 for name in request.GET):
                raise ValueError
            if set(request.GET) == {"request_key"}:
                job = epub_validations.recover(source_id, _key(request.GET["request_key"]))
                if job is None:
                    return response({"error": "This validation request is not recorded yet"}, 404)
                return response(job_data(job))
            if set(request.GET) - {"page"}:
                raise ValueError
            text = request.GET.get("page", "1")
            if (
                not 1 <= len(text) <= 5
                or not text.isascii()
                or not text.isdecimal()
                or not 1 <= int(text) <= 10000
            ):
                raise ValueError
            if not Job.objects.filter(pk=source_id, kind="epub").exists():
                return response({"error": "EPUB inspection not found"}, 404)
            page = int(text)
            rows = Job.objects.filter(kind="epub_validation", input__source_job_id=str(source_id))
            return response(
                {
                    "jobs": [
                        job_data(row)
                        for row in rows.order_by("-created_at", "-id")[(page - 1) * 20 : page * 20]
                    ],
                    "total": rows.count(),
                    "page": page,
                    "page_size": 20,
                }
            )
        if request.GET:
            raise ValueError
        if request.content_type != "application/json":
            return response({"error": "Validation requests take an empty JSON object"}, 415)
        length = request.META.get("CONTENT_LENGTH", "")
        if length and (not length.isascii() or not length.isdecimal()):
            raise ValueError
        significant = length.lstrip("0") or "0"
        if len(significant) > 4 or int(significant) > 1024:
            return response({"error": "Validation requests are limited to 1024 bytes"}, 413)
        key = _key(request.headers.get("Idempotency-Key", ""))
        body = request.read(1025)
        if len(body) > 1024:
            return response({"error": "Validation requests are limited to 1024 bytes"}, 413)
        value = json.loads(body)
        if not isinstance(value, dict) or value:
            raise ValueError
        return response(job_data(epub_validations.enqueue(source_id, key)), 202)
    except ValueError, TypeError, UnicodeError:
        return response(
            {"error": "Use an empty JSON object, one UUID request key and a valid page"}, 400
        )
    except ERRORS as error:
        return response({"error": str(error)}, error.status)


@require_http_methods(["GET"])
def report(request, job_id):
    if request.GET:
        return response({"error": "Report retrieval takes no parameters"}, 400)
    try:
        return response(epub_validations.report(Job.objects.get(pk=job_id)))
    except Job.DoesNotExist:
        return response({"error": "EPUB validation not found"}, 404)
    except ERRORS as error:
        return response({"error": str(error)}, error.status)
