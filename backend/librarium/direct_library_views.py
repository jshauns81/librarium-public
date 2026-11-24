import hashlib
from urllib.parse import quote

from django.http import HttpResponse
from django.views.decorators.http import require_GET

from librarium import direct_library, library_read_model
from librarium.views import response


def parameters(request, allowed):
    if set(request.GET) - allowed or any(len(request.GET.getlist(key)) != 1 for key in request.GET):
        raise ValueError
    token = request.GET.get("inventory", "")
    direct_library.check_token(token)
    return token


def error_reply(error, token=""):
    if error.code == "direct_library_changed":
        library_read_model.refused(token)
    return response({"error": str(error), "code": error.code}, error.status)


def invalid_reply():
    return response(
        {"error": "Use valid library parameters.", "code": "direct_library_request"}, 400
    )


@require_GET
def index(request):
    token = ""
    try:
        token = parameters(request, {"q", "page", "inventory", "order"})
        selected = (
            request.GET.get("q", "").strip(),
            int(request.GET.get("page", "1")),
            token,
            request.GET.get("order", ""),
        )
        # The read model answers when it is serving and current; otherwise the direct reader.
        return response(library_read_model.browse(*selected) or direct_library.browse(*selected))
    except ValueError:
        return invalid_reply()
    except direct_library.DirectLibraryError as error:
        return error_reply(error, token)


@require_GET
def series(request):
    token = ""
    try:
        token = parameters(request, {"name", "inventory"})
        name = request.GET.get("name", "")
        return response(
            library_read_model.series(name, token) or direct_library.series(name, token)
        )
    except ValueError:
        return invalid_reply()
    except direct_library.DirectLibraryError as error:
        return error_reply(error, token)


@require_GET
def book(request, book_id: str):
    token = ""
    try:
        token = parameters(request, {"inventory"})
        return response(direct_library.detail(book_id, token))
    except ValueError:
        return invalid_reply()
    except direct_library.DirectLibraryError as error:
        return error_reply(error, token)


COVER_CACHE = "private, max-age=86400"


@require_GET
def cover(request, book_id: str):
    token = ""
    try:
        token = parameters(request, {"inventory"})
        if not token:
            raise ValueError
        raw, metadata = direct_library.cover(book_id, token)
        etag = '"' + hashlib.sha256(raw).hexdigest() + '"'
        if request.headers.get("If-None-Match") == etag:
            reply = HttpResponse(status=304)
        else:
            reply = HttpResponse(raw, content_type=metadata["media_type"])
            reply["Content-Length"] = str(len(raw))
        # The address names the library inventory, which changes whenever
        # Calibre changes a cover, so a day in the browser cache is safe.
        reply["Cache-Control"] = COVER_CACHE
        reply["ETag"] = etag
        reply["Cross-Origin-Resource-Policy"] = "same-origin"
        reply["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return reply
    except ValueError:
        return invalid_reply()
    except direct_library.DirectLibraryError as error:
        return error_reply(error, token)


MEDIA_TYPES = {"EPUB": "application/epub+zip", "PDF": "application/pdf"}


@require_GET
def book_file(request, book_id: str):
    """The exact recorded file of a pinned library book, read-only, never rendered here."""
    token = ""
    try:
        token = parameters(request, {"inventory", "format"})
        selected = request.GET.get("format", "")
        if not token or not selected:
            raise ValueError
        try:
            with direct_library.open_format(book_id, selected, token) as (stream, info):
                raw = stream.read(direct_library.MAX_FILE + 1)
        except OSError as error:
            raise direct_library.DirectLibraryError(
                "This library file is unavailable.", 404, "direct_library_missing"
            ) from error
        if len(raw) > direct_library.MAX_FILE:
            raise direct_library.DirectLibraryError(
                "This library file is too large to open here.", 413, "direct_library_too_large"
            )
        reply = HttpResponse(
            raw, content_type=MEDIA_TYPES.get(selected, "application/octet-stream")
        )
        reply["Content-Length"] = str(len(raw))
        reply["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(info["name"])
        reply["Cache-Control"] = "private, no-store"
        reply["Cross-Origin-Resource-Policy"] = "same-origin"
        reply["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return reply
    except ValueError:
        return invalid_reply()
    except direct_library.DirectLibraryError as error:
        return error_reply(error, token)
