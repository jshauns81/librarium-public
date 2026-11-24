"""Metadata-only discovery of curated references; never returns locators or private evidence."""

from django.views.decorators.http import require_GET

from librarium import catalogue, content_trust
from librarium.validation import bounded_text
from librarium.views import response


@require_GET
def references(request):
    query = request.GET
    if set(query) != {"version", "sha256", "work"} or any(
        len(query.getlist(name)) != 1 for name in query
    ):
        return response({"error": "Choose one catalogue version, digest and work"}, 400)
    version, sha256, work = query["version"], query["sha256"], query["work"]
    if (
        not catalogue.valid_version(version)
        or not catalogue.DIGEST.fullmatch(sha256)
        or not work
        or not bounded_text(work, 80)
    ):
        return response({"error": "Choose one catalogue version, digest and work"}, 400)
    return response(content_trust.discover(version, sha256, work))
