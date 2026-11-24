"""Authenticated job intent/status and same-origin, source-bound candidate bytes."""

from django.http import HttpResponse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from librarium import cover_candidates, cover_sources
from librarium.cover_candidate_views import KEYS
from librarium.cover_review_views import body, endpoint, parameters
from librarium.models import CoverSearch
from librarium.operator_identity import principal
from librarium.views import response


@require_http_methods(["GET", "POST"])
def searches(request, entry_id):
    def action():
        if request.method == "POST":
            value = body(request, KEYS | {"query", "sources", "image_url"}, {"refresh_browser"})
            row = cover_sources.start(
                entry_id, value, request.headers.get("Idempotency-Key", ""), principal(request)
            )
            return response(cover_sources.data(row), 202)
        parameters(request, set())
        row = CoverSearch.objects.filter(entry_id=entry_id).order_by("-created_at", "-id").first()
        return response(
            {
                "enabled": cover_sources.available(),
                "search": cover_sources.data(row) if row else None,
            }
        )

    return endpoint(request, action)


@require_POST
def cancel(request, entry_id, search_id):
    def action():
        body(request, set())
        if not CoverSearch.objects.filter(pk=search_id, entry_id=entry_id).exists():
            raise ValueError
        return response(cover_sources.cancel(search_id))

    return endpoint(request, action)


@require_GET
def image(request, entry_id, search_id, candidate_id):
    def action():
        parameters(request, set())
        row = (
            CoverSearch.objects.filter(pk=search_id, entry_id=entry_id)
            .select_related("entry")
            .first()
        )
        if row is None:
            raise ValueError
        c = next((c for c in row.candidates if c["id"] == str(candidate_id)), None)
        if c is None:
            raise ValueError
        # Preview freshness has the same native identity/cover check as local choices.
        with cover_sources.cover_reviews.current_entry(row.entry):
            pass
        from librarium import library_read_model
        from librarium.models import CalibreBook

        model = cover_sources.cover_reviews.read_model()
        books = library_read_model.entries(
            CalibreBook.objects.filter(pk=row.entry.calibre_id), model.token
        )
        if not books or cover_candidates.binding_for(row.entry, books[0]) != row.binding:
            raise cover_candidates.ChoiceError("The book changed. Search again.")
        raw = cover_sources.verify_candidate(c)
        reply = HttpResponse(raw, content_type="image/jpeg")
        reply["Content-Length"] = str(len(raw))
        reply["Cross-Origin-Resource-Policy"] = "same-origin"
        reply["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; sandbox"
        return reply

    return endpoint(request, action)
