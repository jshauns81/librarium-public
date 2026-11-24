import hashlib
import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from scripts.registry import lookup

VERSION = "v0.1.0-beta.1"


class Response(io.BytesIO):
    def __init__(self, value, digest=None):
        super().__init__(value)
        self.headers = {"Docker-Content-Digest": digest}


def test_lookup_binds_response_bytes_and_authenticated_scope():
    raw = json.dumps({"config": {"digest": "sha256:" + "a" * 64}}).encode()
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    with patch(
        "scripts.registry.request",
        side_effect=[Response(b'{"token":"private"}'), Response(raw, digest)],
    ) as request:
        assert lookup(VERSION, "secret", "owner") == (digest, json.loads(raw))
    assert request.call_args_list[0].args[0].startswith("https://ghcr.io/token?")
    assert request.call_args_list[1].args == (
        "https://ghcr.io/v2/jshauns81/librarium/manifests/0.1.0-beta.1",
        "Bearer private",
    )


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_registry_errors_never_mean_unused_version(status):
    with (
        patch(
            "scripts.registry.request",
            side_effect=[
                Response(b'{"token":"private"}'),
                urllib.error.HTTPError(
                    "https://ghcr.io", status, "error", {}, io.BytesIO()
                ),
            ],
        ),
        pytest.raises(urllib.error.HTTPError),
    ):
        lookup(VERSION, "secret", "owner")


def test_only_manifest_404_means_absent():
    with patch(
        "scripts.registry.request",
        side_effect=[
            Response(b'{"token":"private"}'),
            urllib.error.HTTPError("https://ghcr.io", 404, "absent", {}, io.BytesIO()),
        ],
    ):
        assert lookup(VERSION, "secret", "owner") is None


def test_tampered_manifest_refused():
    with (
        patch(
            "scripts.registry.request",
            side_effect=[
                Response(b'{"token":"private"}'),
                Response(b"{}", "sha256:" + "a" * 64),
            ],
        ),
        pytest.raises(ValueError, match="digest mismatch"),
    ):
        lookup(VERSION, "secret", "owner")


def test_invalid_version_cannot_request_another_path():
    with patch("scripts.registry.request") as request:
        with pytest.raises(ValueError):
            lookup("../../elsewhere", "secret", "owner")
        request.assert_not_called()


def test_browser_lookup_uses_only_its_fixed_repository():
    raw = json.dumps({"config": {"digest": "sha256:" + "a" * 64}}).encode()
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    with patch(
        "scripts.registry.request",
        side_effect=[Response(b'{"token":"private"}'), Response(raw, digest)],
    ) as request:
        assert lookup(VERSION, "secret", "owner", role="source-browser") == (
            digest,
            json.loads(raw),
        )
    assert (
        "scope=repository:jshauns81/librarium-source-browser:pull"
        in request.call_args_list[0].args[0]
    )
    assert (
        request.call_args_list[1].args[0]
        == "https://ghcr.io/v2/jshauns81/librarium-source-browser/manifests/0.1.0-beta.1"
    )


def test_absent_refuses_partial_pair_before_publication(monkeypatch):
    from scripts import registry

    monkeypatch.setattr("sys.argv", ["registry.py", "absent", VERSION])
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_ACTOR", "owner")
    with (
        patch(
            "scripts.registry.lookup", side_effect=[None, ("sha256:" + "b" * 64, {})]
        ) as read,
        pytest.raises(SystemExit),
    ):
        registry.main()
    assert read.call_count == 2
