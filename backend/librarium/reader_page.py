import hashlib
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, HttpResponseNotModified
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET", "HEAD"])
def reader_page(request, book_id: str):
    """The built reader page; the browser reads the book id from the URL."""
    del book_id
    path = Path(settings.BASE_DIR) / "frontend/dist/reader.html"
    try:
        body = path.read_bytes()
    except FileNotFoundError:
        return HttpResponse(
            "The reader page is not part of this build.",
            status=503,
            content_type="text/plain; charset=utf-8",
        )
    etag = f'"{hashlib.sha256(body).hexdigest()}"'
    result: HttpResponse
    if request.headers.get("If-None-Match") == etag:
        result = HttpResponseNotModified()
    else:
        result = HttpResponse(body, content_type="text/html; charset=utf-8")
    result["ETag"] = etag
    result["Cache-Control"] = "no-cache"
    return result
