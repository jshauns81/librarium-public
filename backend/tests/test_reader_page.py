from pathlib import Path

import pytest
from librarium.headers import READER_POLICY, STRICT_POLICY, policy_for
from test_static_shell import load_wsgi_application, wsgi_request


def directives(policy: str) -> dict[str, list[str]]:
    parsed = {}
    for part in policy.split(";"):
        name, *values = part.split()
        parsed[name] = values
    return parsed


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch, settings, tmp_path: Path, db):
    dist = tmp_path / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Library</title>\n")
    (dist / "reader.html").write_text(
        '<!doctype html><title>Reading</title><script type="module" src="/assets/reader.js">'
        "</script>\n"
    )
    (dist / "assets" / "reader.js").write_text("console.log('reader');\n")
    return load_wsgi_application(monkeypatch, settings, tmp_path), dist


def test_reader_policy_frames_books_but_never_relaxes_scripts():
    policy = directives(READER_POLICY)
    assert policy["script-src"] == ["'self'"]
    assert policy["default-src"] == ["'self'"]
    assert policy["frame-src"] == ["blob:"]
    assert policy["style-src"] == ["'self'", "'unsafe-inline'", "blob:"]
    assert policy["img-src"] == ["'self'", "data:", "blob:"]
    assert policy["font-src"] == ["'self'", "data:", "blob:"]
    assert policy["connect-src"] == ["'self'"]
    for locked in ("object-src", "base-uri", "form-action", "frame-ancestors", "worker-src"):
        assert policy[locked] == ["'none'"]
    assert "'unsafe-eval'" not in READER_POLICY
    assert "script-src-elem" not in policy and "script-src-attr" not in policy


def test_main_policy_is_unchanged_and_strict():
    assert STRICT_POLICY == (
        "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    for path in ("/", "/read", "/read/", "/read/7/file", "/reader.html", "/api/session"):
        assert policy_for(path) == STRICT_POLICY, path
    for path in ("/read/7", "/read/7/", "/read/book%20id"):
        assert policy_for(path) == READER_POLICY, path


def test_reader_route_serves_the_reader_page_under_its_own_policy(built):
    application, _ = built
    status, headers, body = wsgi_request(application, f"/read/7?inventory={'a' * 64}")
    assert status == "200 OK"
    assert body.startswith(b"<!doctype html><title>Reading</title>")
    assert headers["Content-Type"].startswith("text/html")
    assert headers["Content-Security-Policy"] == READER_POLICY
    assert headers["Cache-Control"] == "no-cache"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"

    unchanged, again, empty = wsgi_request(
        application, "/read/7", headers={"If-None-Match": headers["ETag"]}
    )
    assert unchanged == "304 Not Modified"
    assert empty == b""
    assert again["Content-Security-Policy"] == READER_POLICY


def test_everything_else_keeps_the_strict_policy(built):
    application, _ = built
    for path in ("/", "/reader.html", "/assets/reader.js"):
        status, headers, _ = wsgi_request(application, path)
        assert status == "200 OK", path
        assert headers["Content-Security-Policy"] == STRICT_POLICY, path
    status, headers, _ = wsgi_request(application, "/read/7/extra")
    assert status == "404 Not Found"
    assert headers["Content-Security-Policy"] == STRICT_POLICY


def test_reader_route_only_reads(built):
    application, _ = built
    for method in ("POST", "PUT", "DELETE"):
        status, _, body = wsgi_request(application, "/read/7", method=method)
        assert status in {"403 Forbidden", "405 Method Not Allowed"}, method
        assert b"Reading" not in body


def test_missing_reader_build_is_reported(built):
    application, dist = built
    (dist / "reader.html").unlink()
    status, headers, body = wsgi_request(application, "/read/7")
    assert status == "503 Service Unavailable"
    assert headers["Content-Type"].startswith("text/plain")
    assert b"reader" in body
