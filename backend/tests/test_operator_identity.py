import importlib
import io
import json

import pytest
from django.core.handlers.wsgi import WSGIRequest
from librarium.operator_identity import principal


@pytest.fixture
def application(monkeypatch, settings, tmp_path):
    (tmp_path / "frontend/dist").mkdir(parents=True)
    settings.BASE_DIR = tmp_path
    settings.LIBRARIUM_CATALOGUE_DIR = None
    settings.LIBRARIUM_OPERATOR_PROXY_IPS = "192.0.2.10,2001:db8::10"

    def echo(environ, start_response):
        request = WSGIRequest(environ)
        start_response("200 OK", [("Content-Type", "application/json")])
        return [
            json.dumps(
                {
                    "principal": principal(request),
                    "raw_identity": "HTTP_X_LIBRARIUM_OPERATOR" in environ,
                    "remote_user_header": "HTTP_REMOTE_USER" in environ,
                }
            ).encode()
        ]

    monkeypatch.setattr("django.core.wsgi.get_wsgi_application", lambda: echo)
    from librarium import wsgi

    result = importlib.reload(wsgi).application
    yield result
    # Do not leave the echo application installed for other WSGI tests.
    settings.LIBRARIUM_OPERATOR_PROXY_IPS = ""
    monkeypatch.undo()
    importlib.reload(wsgi)


def call(application, **updates):
    environ = {
        "REQUEST_METHOD": "GET",
        "SCRIPT_NAME": "",
        "PATH_INFO": "/api/operator-test",
        "QUERY_STRING": "",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(),
        "REMOTE_ADDR": "192.0.2.10",
        **updates,
    }
    response = application(environ, lambda status, headers, exc_info=None: None)
    try:
        return json.loads(b"".join(response))
    finally:
        if hasattr(response, "close"):
            response.close()


@pytest.mark.parametrize("peer", ["192.0.2.10", "2001:db8::10", "2001:db8:0:0:0:0:0:10"])
def test_only_trusted_peer_can_supply_operator(application, peer):
    assert call(application, REMOTE_ADDR=peer, HTTP_X_LIBRARIUM_OPERATOR="operator") == {
        "principal": "operator",
        "raw_identity": False,
        "remote_user_header": False,
    }


@pytest.mark.parametrize("peer", ["192.0.2.11", "127.0.0.1", "", None, "not-an-ip", "fe80::1%eth0"])
def test_untrusted_peer_and_forwarded_address_cannot_supply_operator(application, peer):
    result = call(
        application,
        REMOTE_ADDR=peer,
        HTTP_X_LIBRARIUM_OPERATOR="operator",
        HTTP_X_FORWARDED_FOR="192.0.2.10",
        HTTP_FORWARDED="for=192.0.2.10",
        REMOTE_USER="forged",
        HTTP_REMOTE_USER="forged",
    )
    assert result == {"principal": None, "raw_identity": False, "remote_user_header": False}


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        " ",
        "operator\n",
        "op\terator",
        "op\x00erator",
        "operator\x7f",
        "opérator",
        "x" * 257,
        "operator,forged",
        "CN=operator,OU=example",
        " operator",
    ],
)
def test_missing_or_malformed_identity_never_creates_principal(application, value):
    assert call(application, HTTP_X_LIBRARIUM_OPERATOR=value)["principal"] is None


@pytest.mark.parametrize("value", ["operator", "a", "x" * 256, "operator.beta-1@example.org"])
def test_stable_principal_is_preserved_without_normalization(application, value):
    assert call(application, HTTP_X_LIBRARIUM_OPERATOR=value)["principal"] == value


def test_http_remote_user_and_preexisting_wsgi_identity_are_always_discarded(application):
    assert call(application, HTTP_REMOTE_USER="forged", REMOTE_USER="forged")["principal"] is None
    assert (
        call(
            application,
            HTTP_REMOTE_USER="forged",
            REMOTE_USER="forged",
            HTTP_X_LIBRARIUM_OPERATOR="operator",
        )["principal"]
        == "operator"
    )


def test_default_off_even_with_trusted_peer_header_and_preexisting_identity(application, settings):
    from librarium import wsgi

    settings.LIBRARIUM_OPERATOR_PROXY_IPS = ""
    disabled = importlib.reload(wsgi).application
    assert call(
        disabled,
        HTTP_X_LIBRARIUM_OPERATOR="operator",
        REMOTE_USER="forged",
        HTTP_REMOTE_USER="forged",
    ) == {
        "principal": None,
        "raw_identity": False,
        "remote_user_header": False,
    }


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "192.0.2.0/24",
        "proxy.example.org",
        "192.0.2.10,",
        "192.0.2.10,,2001:db8::10",
        "fe80::1%eth0",
    ],
)
def test_invalid_proxy_configuration_refuses_startup(application, settings, value):
    from librarium import wsgi

    settings.LIBRARIUM_OPERATOR_PROXY_IPS = value
    with pytest.raises(ValueError, match="LIBRARIUM_OPERATOR_PROXY_IPS"):
        importlib.reload(wsgi)


@pytest.mark.parametrize(
    "headers,peer,expected",
    [
        (b"X-Librarium-Operator: operator\r\n", "192.0.2.10", "operator"),
        (b"X-Librarium-Operator: operator\r\n", "192.0.2.11", None),
        (b"Remote-User: forged\r\nREMOTE_USER: forged\r\n", "192.0.2.10", None),
        (b"X-Librarium-Operator: operator\r\nx-librarium-operator: forged\r\n", "192.0.2.10", None),
        (b"X_Librarium_Operator: forged\r\n", "192.0.2.10", None),
        (b"X-Librarium-Operator: op\xe9rator\r\n", "192.0.2.10", None),
    ],
)
def test_pinned_gunicorn_header_parsing_cannot_bypass_identity(
    application, headers, peer, expected
):
    from gunicorn.config import Config
    from gunicorn.http.parser import RequestParser
    from gunicorn.http.wsgi import create

    config = Config()
    config.set("forwarded_allow_ips", "192.0.2.10")
    config.set("forwarder_headers", "SCRIPT_NAME,PATH_INFO")
    request = next(
        RequestParser(
            config,
            [
                b"GET /api/operator-test HTTP/1.1\r\nHost: testserver\r\n" + headers + b"\r\n",
            ],
            (peer, 12345),
        )
    )
    _, environ = create(request, None, (peer, 12345), ("192.0.2.20", 8123), config)
    assert call(application, **environ)["principal"] == expected


@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize("consumer", ["cover", "search"])
def test_existing_operator_gates_share_the_ingress_principal(monkeypatch, authenticated, consumer):
    from librarium import cover_review_views, cover_source_views, views
    from librarium.operator_identity import TrustedOperatorIdentity

    seen = []

    def search(entry_id, value, key, actor):
        seen.append(actor)
        raise cover_review_views.cover_reviews.ReviewError("identity_observed", 409)

    monkeypatch.setattr(cover_source_views.cover_sources, "start", search)
    monkeypatch.setattr(cover_source_views, "body", lambda request, *keys: {})

    def endpoint(environ, start_response):
        request = WSGIRequest(environ)
        if consumer == "cover":
            reply = cover_review_views.endpoint(
                request,
                lambda: views.response(
                    {
                        "actor": principal(request),
                    }
                ),
            )
        else:
            reply = cover_source_views.searches(request, "entry")
        start_response("200 OK", [])
        return [
            json.dumps({"status": reply.status_code, "body": json.loads(reply.content)}).encode()
        ]

    result = call(
        TrustedOperatorIdentity(endpoint, "192.0.2.10"),
        REQUEST_METHOD="POST",
        CONTENT_TYPE="application/json",
        CONTENT_LENGTH="2",
        **{"wsgi.input": io.BytesIO(b"{}")},
        HTTP_X_LIBRARIUM_OPERATOR="operator" if authenticated else "",
        HTTP_REMOTE_USER="forged",
    )
    if authenticated:
        if consumer == "search":
            assert result["status"] == 409
            assert seen == ["operator"]
        else:
            assert result["status"] == 200
            assert result["body"]["actor"] == "operator"
    else:
        assert result["status"] == 401
        assert result["body"]["code"] == "reviewer_required"
        assert seen == []


@pytest.fixture
def real_application(settings, tmp_path):
    """The unmodified WSGI stack, so Django/WhiteNoise/SecurityHeaders interactions are covered."""
    (tmp_path / "frontend/dist").mkdir(parents=True)
    settings.BASE_DIR = tmp_path
    settings.LIBRARIUM_CATALOGUE_DIR = None
    settings.LIBRARIUM_OPERATOR_PROXY_IPS = "192.0.2.10"
    from django.core.signals import request_finished, request_started
    from django.db import close_old_connections
    from librarium import wsgi

    # As Django's test client does: keep the test transaction's connection open across requests.
    request_started.disconnect(close_old_connections)
    request_finished.disconnect(close_old_connections)
    try:
        yield importlib.reload(wsgi).application
    finally:
        request_started.connect(close_old_connections)
        request_finished.connect(close_old_connections)
        settings.LIBRARIUM_OPERATOR_PROXY_IPS = ""
        importlib.reload(wsgi)


def status_of(application, **updates):
    seen = {}
    environ = {
        "REQUEST_METHOD": "GET",
        "SCRIPT_NAME": "",
        "PATH_INFO": "/api/cover-reviews",
        "QUERY_STRING": "",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(),
        "wsgi.errors": io.StringIO(),
        "REMOTE_ADDR": "192.0.2.10",
        **updates,
    }
    response = application(
        environ, lambda status, headers, exc_info=None: seen.setdefault("status", status)
    )
    try:
        body = b"".join(response)
    finally:
        if hasattr(response, "close"):
            response.close()
    return int(seen["status"].split()[0]), body


@pytest.mark.django_db
def test_real_stack_admits_trusted_operator_and_refuses_spoofs(real_application):
    refused = [
        {},
        {"HTTP_X_LIBRARIUM_OPERATOR": "operator", "REMOTE_ADDR": "192.0.2.11"},
        {"HTTP_REMOTE_USER": "operator"},
        {"REMOTE_USER": "operator", "REMOTE_ADDR": "192.0.2.11"},
        {"HTTP_X_LIBRARIUM_OPERATOR": "operator,operator"},
    ]
    for updates in refused:
        status, body = status_of(real_application, **updates)
        assert status == 401 and b"reviewer_required" in body, updates
    # Past the operator gate the queue answers from its own state (no library here): any
    # application reply other than the gate's refusal or a server error proves the principal.
    status, body = status_of(real_application, HTTP_X_LIBRARIUM_OPERATOR="operator")
    assert status not in {401, 500} and b"reviewer_required" not in body, body[:300]


def test_absent_proxy_configuration_disables_identity():
    from librarium.operator_identity import TrustedOperatorIdentity

    seen = {}
    gate = TrustedOperatorIdentity(lambda environ, start: seen.update(environ) or [], None)
    gate({"REMOTE_ADDR": "192.0.2.10", "HTTP_X_LIBRARIUM_OPERATOR": "operator"}, None)
    assert "REMOTE_USER" not in seen and "HTTP_X_LIBRARIUM_OPERATOR" not in seen
