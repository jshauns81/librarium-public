"""Authenticated choice reads and append-only selection, with no delivery endpoint."""

from django.views.decorators.http import require_http_methods

from librarium import cover_candidates
from librarium.cover_review_views import body, endpoint, parameters
from librarium.operator_identity import principal
from librarium.views import response

KEYS = {"revision", "inventory", "version", "sha256"}


@require_http_methods(["GET", "POST"])
def choices(request, entry_id):
    def action():
        if request.method == "GET":
            parameters(request, KEYS)
            if set(request.GET) != KEYS:
                raise ValueError
            value = dict(request.GET.items())
            revision = value["revision"]
            if (
                not revision.isascii()
                or not revision.isdecimal()
                or len(revision) > 19
                or str(int(revision)) != revision
            ):
                raise ValueError
            value["revision"] = int(revision)
            return response(cover_candidates.choices(entry_id, value)[0])
        value = body(request, KEYS | {"candidate_id", "selection_id"})
        result = cover_candidates.save(
            entry_id, value, request.headers.get("Idempotency-Key", ""), principal(request)
        )
        return response(result, 201)

    return endpoint(request, action)
