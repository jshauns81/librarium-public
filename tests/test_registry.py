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
        "https://ghcr.io/v2/jshauns81/librarium-public/manifests/0.1.0-beta.1",
        "Bearer private",
    )


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_registry_errors_never_mean_unused_version(status):
    with (
        patch(
            "scripts.registry.request",
            side_effect=[
                Response(b'{"token":"private"}'),
                urllib.error.HTTPError("https://ghcr.io", status, "error", {}, io.BytesIO()),
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
        "scope=repository:jshauns81/librarium-public-source-browser:pull"
        in request.call_args_list[0].args[0]
    )
    assert (
        request.call_args_list[1].args[0]
        == "https://ghcr.io/v2/jshauns81/librarium-public-source-browser/manifests/0.1.0-beta.1"
    )


def test_absent_refuses_partial_pair_before_publication(monkeypatch):
    from scripts import registry

    monkeypatch.setattr("sys.argv", ["registry.py", "absent", VERSION, "--commit", "f" * 40])
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_ACTOR", "owner")
    with (
        patch(
            "scripts.registry.lookup", side_effect=[None, None, ("sha256:" + "b" * 64, {})]
        ) as read,
        pytest.raises(SystemExit),
    ):
        registry.main()
    assert read.call_count == 3


def test_absence_checks_version_and_source_tag_for_both_images(monkeypatch):
    from scripts import registry

    sha = "f" * 40
    monkeypatch.setattr("sys.argv", ["registry.py", "absent", VERSION, "--commit", sha])
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_ACTOR", "owner")

    def missing():
        return urllib.error.HTTPError("https://ghcr.io", 404, "absent", {}, io.BytesIO())

    with patch(
        "scripts.registry.request",
        side_effect=[
            response for _ in range(4) for response in (Response(b'{"token":"private"}'), missing())
        ],
    ) as request:
        registry.main()
    urls = {call.args[0] for call in request.call_args_list if "/manifests/" in call.args[0]}
    assert urls == {
        f"https://ghcr.io/v2/jshauns81/{package}/manifests/{tag}"
        for package in ("librarium-public", "librarium-public-source-browser")
        for tag in (VERSION[1:], "sha-" + sha)
    }


@pytest.mark.parametrize(
    "fault", ["none", "public", "foreign", "different source", "wrong config", "partial"]
)
def test_verify_private_pair_binds_both_tags_configs_and_private_packages(fault):
    from scripts import registry

    commit = "f" * 40
    roles = ("application", "source-browser")
    receipt = {"commit": commit, **{role: "sha256:" + char * 64 for role, char in zip(roles, "ab")}}
    expected = {role: "sha256:" + char * 64 for role, char in zip(roles, "cd")}

    def metadata(url, authorization, *, accept):
        assert authorization == "Bearer secret"
        assert accept == "application/vnd.github+json"
        package = url.split("/")[-1]
        assert url == "https://api.github.com/users/jshauns81/packages/container/" + package
        return Response(
            json.dumps(
                {
                    "name": package if fault != "foreign" else "other",
                    "package_type": "container",
                    "visibility": "public" if fault == "public" else "private",
                    "owner": {"login": "jshauns81"},
                }
            ).encode()
        )

    def lookup(tag, credential, actor, *, role):
        assert tag in (VERSION, "sha-" + commit)
        if role == "source-browser" and fault == "partial":
            return None
        digest = (
            "different"
            if fault == "different source" and tag.startswith("sha-")
            else expected[role]
        )
        config = "different" if fault == "wrong config" else receipt[role]
        return digest, {"config": {"digest": config}}

    with (
        patch.object(registry, "request", side_effect=metadata),
        patch.object(registry, "lookup", side_effect=lookup),
    ):
        if fault == "none":
            assert (
                registry.verify_private_pair(VERSION, commit, receipt, "secret", "owner")
                == expected
            )
        else:
            with pytest.raises(ValueError):
                registry.verify_private_pair(VERSION, commit, receipt, "secret", "owner")
