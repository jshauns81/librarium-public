import hashlib
import json

import pytest

from scripts import stage_beta


def test_review_hash_mismatch_refuses_before_registry_or_push(tmp_path, monkeypatch):
    archive = tmp_path / "image.tar.gz"
    archive.write_bytes(b"unreviewed")
    dest = tmp_path / "copy"
    with pytest.raises(ValueError, match="archive hash mismatch"):
        stage_beta.copy_reviewed(archive, dest, "0" * 64)
    assert not dest.exists()


def test_preflight_rejects_wrong_config_digest_or_source_label():
    raw = json.dumps(
        {"config": {"Labels": {"org.opencontainers.image.source": "https://example.org/other"}}}
    ).encode()
    with pytest.raises(ValueError):
        stage_beta.check_config(raw, "sha256:" + hashlib.sha256(raw).hexdigest())
    raw = json.dumps(
        {
            "config": {
                "Labels": {
                    "org.opencontainers.image.source": "https://github.com/jshauns81/librarium-public"
                }
            }
        }
    ).encode()
    with pytest.raises(ValueError):
        stage_beta.check_config(raw, "sha256:" + "0" * 64)


def test_orchestration_rejects_existing_tag_before_any_registry_write(monkeypatch):
    class Registry:
        def __init__(self):
            self.pushed = False

        def preflight(self, version, commit):
            raise ValueError("occupied")

        def push(self, *args):
            self.pushed = True

    client = Registry()
    with pytest.raises(ValueError, match="occupied"):
        stage_beta.publish_pair(client, {}, "v0.1.0-beta.1", "a" * 40, {})
    assert not client.pushed


def test_preflight_rejects_public_package_without_registry_write(monkeypatch):
    class Response:
        def __init__(self, data):
            self.data = data
            self.headers = {"X-OAuth-Scopes": "write:packages"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, *args):
            return json.dumps(self.data).encode()

    client = stage_beta.Stager("fake", "jshauns81", "unused")

    def api(path):
        if path == "/user":
            return Response({"login": "jshauns81"})
        if path.startswith("/user/packages"):
            return Response([])
        return Response(
            {
                "visibility": "public",
                "name": "librarium-public",
                "owner": {"login": "jshauns81"},
                "package_type": "container",
            }
        )

    monkeypatch.setattr(client, "api", api)
    with pytest.raises(ValueError, match="private owner package"):
        client.preflight("v0.1.0-beta.1", "a" * 40)


def test_preflight_rejects_missing_write_scope_before_package_checks(monkeypatch):
    class Response:
        def __init__(self):
            self.headers = {"X-OAuth-Scopes": "read:packages"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, *args):
            return b'{"login":"jshauns81"}'

    client = stage_beta.Stager("fake", "jshauns81", "unused")
    monkeypatch.setattr(client, "api", lambda path: Response())
    with pytest.raises(ValueError, match="package scopes"):
        client.preflight("v0.1.0-beta.1", "a" * 40)


def test_copy_reviewed_rejects_symlink_without_copying(tmp_path):
    original = tmp_path / "input"
    original.write_bytes(b"image")
    link = tmp_path / "link"
    link.symlink_to(original)
    with pytest.raises(OSError):
        stage_beta.copy_reviewed(link, tmp_path / "copy", hashlib.sha256(b"image").hexdigest())
    assert not (tmp_path / "copy").exists()


def test_pair_verification_occurs_only_after_both_pushes(monkeypatch):
    events = []

    class Client:
        credential = "fake"
        actor = "fake"

        def preflight(self, *args):
            events.append("preflight")

        def push(self, role, *args):
            events.append(role)

    def verify(*args):
        events.append("verify")
        return {"ok": True}

    monkeypatch.setattr(stage_beta.registry, "verify_private_pair", verify)
    assert stage_beta.publish_pair(
        Client(), {"application": 1, "source-browser": 2}, "v0.1.0-beta.1", "a" * 40, {}
    ) == {"ok": True}
    assert events == ["preflight", "application", "source-browser", "verify"]


def test_missing_packages_require_authenticated_owner_list_access(monkeypatch):
    import urllib.error

    class Response:
        def __init__(self, value):
            self.value = value
            self.headers = {"X-OAuth-Scopes": "write:packages"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, *args):
            return json.dumps(self.value).encode()

    client = stage_beta.Stager("fake", "jshauns81", "unused")

    def api(path):
        if path == "/user":
            return Response({"login": "jshauns81"})
        if path.startswith("/user/packages?"):
            return Response([])
        raise urllib.error.HTTPError("https://api.github.com/", 404, "missing", {}, None)

    monkeypatch.setattr(client, "api", api)
    monkeypatch.setattr(
        stage_beta.registry, "lookup", lambda *a, **k: pytest.fail("missing package lookup")
    )
    client.preflight("v0.1.0-beta.1", "a" * 40)
    assert client.absent_packages == {"application", "source-browser"}


def test_failure_on_second_image_never_reports_success(monkeypatch):
    events = []

    class Client:
        credential = "fake"
        actor = "fake"

        def preflight(self, *args):
            pass

        def push(self, role, *args):
            events.append(role)
            if role == "source-browser":
                raise ValueError("copy failed")

    monkeypatch.setattr(
        stage_beta.registry,
        "verify_private_pair",
        lambda *args: pytest.fail("must not verify incomplete pair"),
    )
    with pytest.raises(ValueError, match="copy failed"):
        stage_beta.publish_pair(
            Client(), {"application": 1, "source-browser": 2}, "v0.1.0-beta.1", "a" * 40, {}
        )
    assert events == ["application", "source-browser"]


def test_stage_push_copies_verified_manifest_by_digest(monkeypatch):
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, *args):
            return json.dumps(
                {
                    "visibility": "private",
                    "name": "librarium-public",
                    "owner": {"login": "jshauns81"},
                    "package_type": "container",
                }
            ).encode()

    client = stage_beta.Stager("credential-not-in-command", "jshauns81", "authfile", "policy")
    client.absent_packages.add("application")
    monkeypatch.setattr(client, "api", lambda path: Response())
    image_id = "sha256:" + "b" * 64
    digest = "sha256:" + "c" * 64
    monkeypatch.setattr(
        stage_beta.registry,
        "lookup",
        lambda ref, *args, **kwargs: (
            None if ref.startswith("sha-") else (digest, {"config": {"digest": image_id}})
        ),
    )
    monkeypatch.setattr(stage_beta, "run_skopeo", lambda args, **kwargs: calls.append(args))
    client.push(
        "application", "reviewed.tar.gz", "v0.1.0-beta.1", "a" * 40, {"application": image_id}
    )
    assert len(calls) == 2
    assert calls[0][-1].endswith(":0.1.0-beta.1")
    assert calls[1][-2].endswith("@" + digest)
    assert calls[1][-1].endswith(":sha-" + "a" * 40)
    assert "--preserve-digests" in calls[1]
    assert all("credential-not-in-command" not in arg for call in calls for arg in call)
