import importlib
import io
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest


def wsgi_request(
    application, path: str, headers: dict[str, str] | None = None, method: str = "GET"
):
    parsed = urlsplit(path)
    environ = {
        "REQUEST_METHOD": method,
        "SCRIPT_NAME": "",
        "PATH_INFO": parsed.path,
        "QUERY_STRING": parsed.query,
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "HTTP_HOST": "testserver",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(),
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    for key, value in (headers or {}).items():
        header_key = f"HTTP_{key.upper().replace('-', '_')}"
        environ[header_key] = value

    captured: list[tuple[str, dict[str, str]]] = []

    def start_response(status, response_headers, exc_info=None):
        del exc_info
        captured.append((status, dict(response_headers)))

    response = application(environ, start_response)
    try:
        body = b"".join(response)
    finally:
        if hasattr(response, "close"):
            response.close()
    status, response_headers = captured[0]
    return status, response_headers, body


def load_wsgi_application(monkeypatch: pytest.MonkeyPatch, settings, base_dir: Path):
    monkeypatch.setattr(settings, "BASE_DIR", base_dir)
    monkeypatch.setattr(settings, "LIBRARIUM_CATALOGUE_DIR", None)
    from librarium import wsgi

    return importlib.reload(wsgi).application


@pytest.mark.django_db
def test_html_shell_revalidates_while_preserving_asset_security_and_api_headers(
    monkeypatch: pytest.MonkeyPatch,
    settings,
    tmp_path: Path,
):
    dist = tmp_path / "frontend" / "dist"
    assets = dist / "assets"
    nested = dist / "nested"
    assets.mkdir(parents=True)
    nested.mkdir(parents=True)

    (dist / "index.html").write_text(
        '<!doctype html><script type="module" src="/assets/index-old11111.js"></script>\n',
        encoding="utf-8",
    )
    (dist / "shell.html").write_text("<!doctype html><title>Shell</title>\n", encoding="utf-8")
    (nested / "index.html").write_text("<!doctype html><title>Nested</title>\n", encoding="utf-8")
    (assets / "index-old11111.js").write_text("console.log('old');\n", encoding="utf-8")
    (assets / "index-BRpGa1jN.css").write_text("body { margin: 0; }\n", encoding="utf-8")

    application = load_wsgi_application(monkeypatch, settings, tmp_path)

    for html_path in ("/", "/shell.html", "/nested/"):
        status, headers, body = wsgi_request(application, html_path)
        assert status == "200 OK"
        assert body.startswith(b"<!doctype html>")
        assert headers["Content-Type"].startswith("text/html")
        assert headers["Cache-Control"] == "no-cache"
        assert "ETag" in headers
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert "default-src 'self'" in headers["Content-Security-Policy"]

    for asset_path in ("/assets/index-old11111.js", "/assets/index-BRpGa1jN.css"):
        status, headers, _ = wsgi_request(application, asset_path)
        assert status == "200 OK"
        assert headers["Cache-Control"] == "max-age=60, public"
        assert "ETag" in headers
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["X-Content-Type-Options"] == "nosniff"

    api_status, api_headers, _ = wsgi_request(application, "/api/session")
    assert api_status == "200 OK"
    assert api_headers["Cache-Control"] == "no-store"
    assert api_headers["X-Frame-Options"] == "DENY"
    assert api_headers["X-Content-Type-Options"] == "nosniff"


def test_conditional_requests_are_not_stale_after_new_build_and_new_instance(
    monkeypatch: pytest.MonkeyPatch,
    settings,
    tmp_path: Path,
):
    dist = tmp_path / "frontend" / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)

    index_file = dist / "index.html"
    old_html = '<!doctype html><script type="module" src="/assets/index-old11111.js"></script>\n'
    new_html = '<!doctype html><script type="module" src="/assets/index-new22222.js"></script>\n'
    assert len(old_html) == len(new_html)

    index_file.write_text(old_html, encoding="utf-8")
    fixed_mtime = 1_761_447_700
    os.utime(index_file, (fixed_mtime, fixed_mtime))

    first_instance = load_wsgi_application(monkeypatch, settings, tmp_path)
    status1, headers1, body1 = wsgi_request(first_instance, "/")
    assert status1 == "200 OK"
    assert headers1["Cache-Control"] == "no-cache"
    assert b"/assets/index-old11111.js" in body1

    unchanged_status, unchanged_headers, unchanged_body = wsgi_request(
        first_instance,
        "/",
        headers={
            "If-None-Match": headers1["ETag"],
            "If-Modified-Since": headers1["Last-Modified"],
        },
    )
    assert unchanged_status == "304 Not Modified"
    assert unchanged_headers["Cache-Control"] == "no-cache"
    assert unchanged_headers["ETag"] == headers1["ETag"]
    assert unchanged_body == b""

    # Simulate a new dist build (same byte length, even within the same second) and worker reload.
    index_file.write_text(new_html, encoding="utf-8")
    os.utime(index_file, (fixed_mtime, fixed_mtime))
    second_instance = load_wsgi_application(monkeypatch, settings, tmp_path)

    status2, headers2, body2 = wsgi_request(
        second_instance,
        "/",
        headers={
            "If-None-Match": headers1["ETag"],
            "If-Modified-Since": headers1["Last-Modified"],
        },
    )
    assert status2 == "200 OK"
    assert headers2["Cache-Control"] == "no-cache"
    assert headers2["ETag"] != headers1["ETag"]
    assert b"/assets/index-new22222.js" in body2
