import copy
import hashlib
import io
import json
import os
import subprocess
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import promotion, release

SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64
BROWSER_DIGEST = "sha256:" + "e" * 64
IMAGE_ID = "sha256:" + "f" * 64
BROWSER_ID = "sha256:" + "a" * 64
REPO = "https://github.com/jshauns81/librarium"
NOW = datetime(2026, 10, 30, tzinfo=UTC)


def inputs(**changes):
    values = {
        "beta": "v0.1.0-beta.2",
        "source": SHA,
        "digest": DIGEST,
        "browser_digest": BROWSER_DIGEST,
        "stable": "v0.1.0",
        "issue": "47",
        "comment": "123",
        "confirmation": "PROMOTE",
    }
    return promotion.Inputs(**(values | changes))


def acceptance():
    return {
        "schema": "librarium.beta-acceptance.v2",
        "repository": REPO,
        "beta": "v0.1.0-beta.2",
        "source_sha": SHA,
        "image_digest": DIGEST,
        "source_browser_digest": BROWSER_DIGEST,
        "observation": {
            "started_at": "2026-10-27T00:00:00Z",
            "ended_at": "2026-10-29T00:00:00Z",
        },
        "representative_session": {
            "complete": True,
            "evidence": [REPO + "/issues/47#issuecomment-124"],
        },
        "restart_reconnect": {
            "complete": True,
            "evidence": [REPO + "/issues/47#issuecomment-125"],
        },
        "blocking_defects": [],
    }


def comment(body=None, number=123):
    return {
        "id": number,
        "user": {"login": "jshauns81", "id": 57206355, "type": "User"},
        "author_association": "OWNER",
        "created_at": "2026-10-29T01:00:00Z",
        "updated_at": "2026-10-29T01:00:00Z",
        "issue_url": "https://api.github.com/repos/jshauns81/librarium/issues/47",
        "html_url": REPO + f"/issues/47#issuecomment-{number}",
        "body": json.dumps(acceptance()) if body is None else body,
    }


class API:
    def __init__(self):
        self.comments = {
            123: comment(),
            124: comment("Authenticated release journeys passed", 124),
            125: comment("Restart and reconnect passed", 125),
        }

    def get(self, path, **kwargs):
        return copy.deepcopy(self.comments[int(path.rsplit("/", 1)[1])])


@pytest.mark.parametrize(
    "changes",
    [
        {"beta": "v0.1.0"},
        {"source": "main"},
        {"digest": "latest"},
        {"browser_digest": "latest"},
        {"stable": "v0.1.1"},
        {"stable": "v01.1.0"},
        {"confirmation": "promote"},
        {"issue": "../47"},
        {"comment": "0"},
        {"issue": True},
    ],
)
def test_invalid_inputs_refused_before_network(changes):
    with pytest.raises(ValueError):
        inputs(**changes)


def test_owner_attestation_binds_identity_interval_and_evidence_hashes():
    api = API()
    proof = promotion.acceptance_record(api, inputs(), "2026-10-26T23:00:00Z", NOW)
    assert (
        proof["body_sha256"]
        == hashlib.sha256(api.comments[123]["body"].encode()).hexdigest()
    )
    assert proof["url"] == REPO + "/issues/47#issuecomment-123"
    assert len(proof["evidence"]) == 2
    assert proof["evidence"][0]["author"]["login"] == "jshauns81"
    assert (
        proof["evidence"][0]["body_sha256"]
        == hashlib.sha256(api.comments[124]["body"].encode()).hexdigest()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("user", {"login": "someone", "type": "User", "id": 1}),
        ("user", {"login": "jshauns81", "type": "Bot", "id": 57206355}),
        ("user", {"login": "jshauns81", "type": "User", "id": 1}),
        ("author_association", "COLLABORATOR"),
        ("updated_at", "2026-10-29T02:00:00Z"),
        ("issue_url", "https://api.github.com/repos/someone/else/issues/47"),
        ("html_url", REPO + "/issues/48#issuecomment-123"),
    ],
)
def test_acceptance_refuses_wrong_author_edited_or_unbound_comment(field, value):
    api = API()
    api.comments[123][field] = value
    with pytest.raises(ValueError):
        promotion.acceptance_record(api, inputs(), "2026-10-26T23:00:00Z", NOW)


@pytest.mark.parametrize(
    "change",
    [
        lambda x: x.update(beta="v0.1.0-beta.1"),
        lambda x: x.update(source_sha="c" * 40),
        lambda x: x.update(image_digest="sha256:" + "c" * 64),
        lambda x: x.update(source_browser_digest="sha256:" + "c" * 64),
        lambda x: x.update(repository="https://github.com/someone/else"),
        lambda x: x["observation"].update(ended_at="2026-10-28T23:59:59Z"),
        lambda x: x["observation"].update(started_at="2026-10-26T22:59:59Z"),
        lambda x: x["observation"].update(ended_at="2026-10-29T02:00:00Z"),
        lambda x: x["observation"].update(started_at="2026-10-27T00:00:00"),
        lambda x: x["representative_session"].update(complete=1),
        lambda x: x["restart_reconnect"].update(complete=False),
        lambda x: x["representative_session"].update(evidence=[]),
        lambda x: x["restart_reconnect"].update(
            evidence=["https://evil.invalid/secret"]
        ),
        lambda x: x.update(blocking_defects=["lost action"]),
        lambda x: x.update(unexpected=True),
    ],
)
def test_acceptance_cannot_assert_incomplete_or_different_beta(change):
    api = API()
    data = acceptance()
    change(data)
    api.comments[123]["body"] = json.dumps(data)
    with pytest.raises(ValueError):
        promotion.acceptance_record(api, inputs(), "2026-10-26T23:00:00Z", NOW)


@pytest.mark.parametrize(
    "body", ['{"schema":1,"schema":2}', '{"a":NaN}', "```json\n{}\n```"]
)
def test_noncanonical_json_documents_are_refused(body):
    api = API()
    api.comments[123]["body"] = body
    with pytest.raises(ValueError):
        promotion.acceptance_record(api, inputs(), "2026-10-26T23:00:00Z", NOW)


def test_future_acceptance_and_evidence_in_wrong_issue_refused():
    api = API()
    api.comments[124]["issue_url"] += "0"
    with pytest.raises(ValueError):
        promotion.acceptance_record(api, inputs(), "2026-10-26T23:00:00Z", NOW)
    with pytest.raises(ValueError):
        promotion.acceptance_record(
            API(), inputs(), "2026-10-26T23:00:00Z", datetime(2026, 10, 28, tzinfo=UTC)
        )


class Response(io.BytesIO):
    def __init__(self, raw=b"{}", status=200, headers=None):
        super().__init__(raw)
        self.status = status
        self.headers = headers or {}


@pytest.mark.parametrize("status", [301, 307, 401, 403, 429, 500])
def test_api_errors_never_mean_an_unused_stable_version(status):
    error = urllib.error.HTTPError(
        "https://api.github.com", status, "failure", {}, io.BytesIO()
    )
    with (
        patch("scripts.promotion.open_request", side_effect=error),
        pytest.raises(urllib.error.HTTPError),
    ):
        promotion.GitHub("private").get("/releases/tags/v0.1.0", missing=True)


def test_only_explicit_github_404_is_absence():
    error = urllib.error.HTTPError(
        "https://api.github.com", 404, "missing", {}, io.BytesIO()
    )
    with patch("scripts.promotion.open_request", side_effect=error):
        assert (
            promotion.GitHub("private").get("/releases/tags/v0.1.0", missing=True)
            is None
        )


def test_asset_signed_redirect_never_receives_credentials_and_hash_is_checked():
    raw = b'{"schema":"fixture"}'
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    redirect = urllib.error.HTTPError(
        "https://api.github.com",
        302,
        "download",
        {
            "Location": "https://release-assets.githubusercontent.com/asset?signature=private"
        },
        io.BytesIO(),
    )
    with patch(
        "scripts.promotion.open_request", side_effect=[redirect, Response(raw)]
    ) as request:
        assert (
            promotion.GitHub("private").asset(
                {"id": 12, "size": len(raw), "digest": digest}
            )
            == raw
        )
    first, second = [call.args[0] for call in request.call_args_list]
    assert first.get_header("Authorization") == "Bearer private"
    assert second.get_header("Authorization") is None
    assert second.get_header("Cookie") is None


@pytest.mark.parametrize(
    "url",
    [
        "http://release-assets.githubusercontent.com/a",
        "https://evil.invalid/a",
        "https://release-assets.githubusercontent.com.evil.invalid/a",
        "https://user@release-assets.githubusercontent.com/a",
        "https://release-assets.githubusercontent.com:443/a",
    ],
)
def test_asset_refuses_every_other_redirect(url):
    redirect = urllib.error.HTTPError(
        "https://api.github.com", 302, "download", {"Location": url}, io.BytesIO()
    )
    with (
        patch("scripts.promotion.open_request", side_effect=redirect) as request,
        pytest.raises(ValueError),
    ):
        promotion.GitHub("private").asset(
            {"id": 12, "size": 2, "digest": "sha256:" + "a" * 64}
        )
    assert request.call_count == 1


def test_asset_tampering_and_second_redirect_refuse():
    redirect = urllib.error.HTTPError(
        "https://api.github.com",
        302,
        "download",
        {"Location": "https://release-assets.githubusercontent.com/a"},
        io.BytesIO(),
    )
    with (
        patch("scripts.promotion.open_request", side_effect=[redirect, redirect]),
        pytest.raises(urllib.error.HTTPError),
    ):
        promotion.GitHub("private").asset(
            {"id": 12, "size": 2, "digest": "sha256:" + "a" * 64}
        )


CONTAINER_STEPS = [
    "Check actual packaged application",
    "Verify state survives container replacement",
    "Inspect a preserved synthetic EPUB through the optional persistent file role",
    "Exercise database and artifact backup/restore in disposable state",
    "Prove composed runtime startup and fresh-cluster recovery",
    "Prove released-image configuration compatibility",
    "Retain portable runtime-startup proofs",
    "Export the candidate for isolated upgrade acceptance",
    "Source browser isolation and Chromium sandbox",
    "Export the accepted source browser",
]
UPGRADE_STEPS = [
    "Load the exact accepted candidate image",
    "Populated historical-source upgrade and both-generation recovery",
    "Copy portable proof for artifact upload",
    "Retain portable synthetic proof only",
]
AGGREGATE_STEPS = ["Require selected acceptance and report deferred tiers"]
PACKAGED_STEPS = {
    "acceptance / candidate-container": CONTAINER_STEPS,
    "acceptance / populated-upgrade": UPGRADE_STEPS,
    "acceptance / container": AGGREGATE_STEPS,
}
QUALITY_STEPS = [
    "Frozen dependencies and isolated native inputs",
    "Python tests, types, lint and migration checks",
    "Frontend tests, types, build and format",
    "Dependency security audits",
]
RUN = REPO + "/actions/runs/9"


class FullAPI(API):
    def __init__(self):
        super().__init__()
        self.writes = []
        self.raw = json.dumps(
            release.manifest(
                "v0.1.0-beta.2",
                SHA,
                DIGEST,
                RUN,
                browser_digest=BROWSER_DIGEST,
                image_id=IMAGE_ID,
                browser_image_id=BROWSER_ID,
            )
        ).encode()
        self.asset_metadata = {
            "id": 15,
            "name": "release-manifest.json",
            "state": "uploaded",
            "size": len(self.raw),
            "digest": "sha256:" + hashlib.sha256(self.raw).hexdigest(),
            "updated_at": "2026-10-26T23:00:00Z",
        }
        self.stack_raw = release.stack_archive()
        self.stack_metadata = {
            "id": 16,
            "name": "stack-assets.zip",
            "state": "uploaded",
            "size": len(self.stack_raw),
            "digest": "sha256:" + promotion.sha(self.stack_raw),
            "updated_at": "2026-10-26T23:00:00Z",
        }
        self.run = {
            "id": 9,
            "html_url": RUN,
            "path": ".github/workflows/beta.yml",
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": SHA,
            "repository": {"full_name": promotion.REPO},
            "head_repository": {"full_name": promotion.REPO},
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 1,
            "workflow_id": 29,
        }
        self.jobs = []
        for index, name in enumerate(
            [
                "validate",
                "quality / source-quality",
                "acceptance / candidate-container",
                "acceptance / populated-upgrade",
                "acceptance / container",
                "publish",
            ]
        ):
            names = (
                QUALITY_STEPS
                if name == "quality / source-quality"
                else PACKAGED_STEPS.get(name, [])
            )
            self.jobs.append(
                {
                    "id": index + 1,
                    "name": name,
                    "run_id": 9,
                    "run_attempt": 1,
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [
                        {"name": name, "status": "completed", "conclusion": "success"}
                        for name in names
                    ],
                }
            )
        self.beta = {
            "id": 19,
            "tag_name": "v0.1.0-beta.2",
            "draft": False,
            "prerelease": True,
            "html_url": REPO + "/releases/tag/v0.1.0-beta.2",
            "published_at": "2026-10-26T23:00:00Z",
            "updated_at": "2026-10-26T23:00:00Z",
            "assets": [self.asset_metadata, self.stack_metadata],
            "body": "Reviewed candidate changes, limitations and recovery instructions.",
        }
        self.tag = {
            "ref": "refs/tags/v0.1.0-beta.2",
            "object": {"type": "tag", "sha": "c" * 40},
        }
        self.annotated = {
            "tag": "v0.1.0-beta.2",
            "object": {
                "type": "commit",
                "sha": SHA,
                "url": promotion.API + "/git/commits/" + SHA,
            },
        }
        self.stable = None
        self.stable_ref = None

    def get(self, path, missing=False):
        if path.startswith("/issues/comments/"):
            return super().get(path)
        mapping = {
            "/releases/tags/v0.1.0-beta.2": self.beta,
            "/git/ref/tags/v0.1.0-beta.2": self.tag,
            "/git/tags/" + "c" * 40: self.annotated,
            "/actions/runs/9": self.run,
            "/actions/runs/9/attempts/1/jobs?per_page=100": {
                "jobs": self.jobs,
                "total_count": len(self.jobs),
            },
            "/releases/latest": self.stable,
            "/releases/tags/v0.1.0": self.stable,
            "/git/ref/tags/v0.1.0": self.stable_ref,
            "/git/tags/" + "d" * 40: {
                "tag": "v0.1.0",
                "object": {"type": "commit", "sha": SHA},
            },
        }
        value = mapping[path]
        assert value is not None or missing
        return copy.deepcopy(value)

    def asset(self, metadata):
        if metadata["id"] == 16:
            return self.stack_raw
        if metadata["id"] == 32:
            return self.stable_stack_raw
        return self.raw if metadata["id"] == 15 else self.stable_raw

    def write(self, path, data, **kwargs):
        self.writes.append((path, copy.deepcopy(data)))
        if path == "/git/tags":
            return {"sha": "d" * 40}
        if path == "/git/refs":
            self.stable_ref = {"object": {"type": "tag", "sha": data["sha"]}}
            return self.stable_ref
        if path == "/releases":
            self.stable = data | {"id": 30}
            return self.stable
        if path.startswith("/releases/30/assets"):
            is_stack = "stack-assets.zip" in path
            if is_stack:
                self.stable_stack_raw = data
            else:
                self.stable_raw = data
            metadata = {
                "id": 32 if is_stack else 31,
                "name": "stack-assets.zip" if is_stack else "release-manifest.json",
                "state": "uploaded",
                "size": len(data),
                "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            }
            self.stable.setdefault("assets", []).append(metadata)
            return metadata
        if path == "/releases/30":
            self.stable.update(data)
            return self.stable
        raise AssertionError(path)


class FullRegistry:
    def __init__(self):
        self.image = {
            "raw": b"exact existing image bytes",
            "digest": DIGEST,
            "media": "application/vnd.oci.image.manifest.v1+json",
        }
        self.image["raw"] = json.dumps({"config": {"digest": IMAGE_ID}}).encode()
        self.browser = dict(
            self.image,
            digest=BROWSER_DIGEST,
            raw=json.dumps({"config": {"digest": BROWSER_ID}}).encode(),
        )
        self.stable = None
        self.browser_stable = None
        self.writes = []

    def lookup(self, ref, role="application"):
        if role == "source-browser":
            return self.browser_stable if ref == "v0.1.0" else self.browser
        return self.stable if ref == "v0.1.0" else self.image

    def copy(self, image, destination, role="application"):
        assert self.lookup(destination, role) is None
        self.writes.append((image, destination, role))
        if role == "source-browser":
            self.browser_stable = image
        else:
            self.stable = image


@pytest.fixture
def full_verification():
    with (
        patch(
            "scripts.promotion.git",
            side_effect=lambda root, *args: SHA if args[0] == "rev-parse" else "",
        ),
        patch("scripts.promotion.subprocess.run"),
    ):
        yield FullAPI(), FullRegistry()


def test_complete_verification_is_read_only_and_binds_actual_source(full_verification):
    api, registry = full_verification
    proof = promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)
    assert proof["manifest"]["compatibility"] == release.compatibility()
    assert (
        proof["beta_notes_sha256"]
        == hashlib.sha256(api.beta["body"].encode()).hexdigest()
    )
    assert api.writes == registry.writes == []


def test_split_acceptance_jobs_verify_and_retain_each_step(full_verification):
    api, registry = full_verification
    proof = promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)
    jobs = {job["name"]: job for job in proof["beta_run"]["jobs"]}
    for name, required in PACKAGED_STEPS.items():
        assert {step["name"] for step in jobs[name]["steps"]} == set(required)
    assert api.writes == registry.writes == []


@pytest.mark.parametrize("name", PACKAGED_STEPS)
@pytest.mark.parametrize("change", ["missing", "skipped"])
def test_each_split_acceptance_job_is_required(full_verification, name, change):
    api, registry = full_verification
    job = next(job for job in api.jobs if job["name"] == name)
    if change == "missing":
        api.jobs.remove(job)
    else:
        job["conclusion"] = "skipped"
    with pytest.raises(ValueError):
        promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)
    assert api.writes == registry.writes == []


@pytest.mark.parametrize(
    "name,step",
    [(name, step) for name, steps in PACKAGED_STEPS.items() for step in steps],
)
@pytest.mark.parametrize("change", ["missing", "skipped", "duplicate"])
def test_each_split_acceptance_step_is_required(full_verification, name, step, change):
    api, registry = full_verification
    job = next(job for job in api.jobs if job["name"] == name)
    record = next(record for record in job["steps"] if record["name"] == step)
    if change == "missing":
        job["steps"].remove(record)
    elif change == "skipped":
        record["conclusion"] = "skipped"
    else:
        job["steps"].append(copy.deepcopy(record))
    with pytest.raises(ValueError):
        promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)
    assert api.writes == registry.writes == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a, r: a.beta.update(draft=True),
        lambda a, r: a.beta.update(prerelease=False),
        lambda a, r: a.tag["object"].update(type="commit"),
        lambda a, r: a.annotated["object"].update(sha="e" * 40),
        lambda a, r: a.run.update(head_sha="e" * 40),
        lambda a, r: a.run.update(path=".github/workflows/other.yml"),
        lambda a, r: a.run["head_repository"].update(full_name="other/repo"),
        lambda a, r: a.jobs[1].update(conclusion="skipped"),
        lambda a, r: a.jobs[1].update(run_attempt=2),
        lambda a, r: a.jobs[1]["steps"][0].update(conclusion="skipped"),
        lambda a, r: a.jobs[2]["steps"][2].update(conclusion="skipped"),
        lambda a, r: a.jobs.pop(),
        lambda a, r: a.comments[123].update(updated_at="2026-10-29T02:00:00Z"),
        lambda a, r: r.image.update(digest="sha256:" + "e" * 64),
        lambda a, r: setattr(r, "stable", dict(r.image)),
        lambda a, r: setattr(
            a, "stable_ref", {"object": {"type": "tag", "sha": "e" * 40}}
        ),
        lambda a, r: setattr(
            a, "stable", {"tag_name": "v0.1.0", "draft": True, "prerelease": False}
        ),
    ],
)
def test_verification_refusals_perform_no_publication(full_verification, mutate):
    api, registry = full_verification
    mutate(api, registry)
    with pytest.raises(ValueError):
        promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)
    assert api.writes == registry.writes == []


def test_manifest_compatibility_or_fields_cannot_be_omitted(full_verification):
    api, registry = full_verification
    data = json.loads(api.raw)
    data["compatibility"]["inspection_policy"] = "newer-policy"
    api.raw = json.dumps(data).encode()
    with pytest.raises(ValueError, match="source compatibility"):
        promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)


@pytest.mark.parametrize(
    "legacy",
    [
        lambda d: d.update(schema="librarium.release.v1"),
        lambda d: d.pop("images"),
        lambda d: d["images"].pop("source-browser"),
    ],
)
def test_single_image_release_is_refused_with_a_clear_reason(full_verification, legacy):
    api, registry = full_verification
    data = json.loads(api.raw)
    legacy(data)
    api.raw = json.dumps(data).encode()
    with pytest.raises(ValueError, match="paired-image release manifest required"):
        promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)
    assert api.writes == registry.writes == []


def test_dirty_source_cannot_supply_compatibility(full_verification):
    api, registry = full_verification
    with (
        patch(
            "scripts.promotion.git",
            side_effect=[SHA, " M backend/librarium/epub_inspection.py"],
        ),
        pytest.raises(ValueError, match="clean checkout"),
    ):
        promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)
    assert api.writes == registry.writes == []


def test_new_comment_or_notes_between_preflight_and_publish_refuses_without_writes(
    full_verification,
):
    api, registry = full_verification
    proof = promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)
    expected = promotion.sha(promotion.canonical(proof))
    api.beta["body"] += " Edited after preflight."
    changed = promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)
    with (
        patch("scripts.promotion.verify", return_value=changed),
        pytest.raises(ValueError, match="changed since preflight"),
    ):
        promotion.publish(
            api, registry, inputs(), release.ROOT, expected, REPO + "/actions/runs/10"
        )
    assert api.writes == registry.writes == []


def test_promotion_copies_bytes_and_publishes_same_source_with_verified_assets(
    full_verification,
):
    api, registry = full_verification
    proof = promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)
    expected = promotion.sha(promotion.canonical(proof))
    with patch("scripts.promotion.verify", return_value=proof):
        manifest = promotion.publish(
            api, registry, inputs(), release.ROOT, expected, REPO + "/actions/runs/10"
        )
    assert registry.writes == [
        (registry.image, "v0.1.0", "application"),
        (registry.browser, "v0.1.0", "source-browser"),
    ]
    assert manifest["images"]["source-browser"]["image"].endswith(BROWSER_DIGEST)
    assert api.stable_stack_raw == api.stack_raw
    assert manifest["image"] == "ghcr.io/jshauns81/librarium@" + DIGEST
    assert manifest["commit"] == SHA and manifest["channel"] == "stable"
    assert (
        manifest["promotion"]["beta_acceptance"]["body_sha256"]
        == proof["beta_acceptance"]["body_sha256"]
    )
    assert api.writes[0][1]["object"] == SHA
    assert api.stable["draft"] is False and api.stable["make_latest"] == "true"
    assert api.beta["body"] in api.stable["body"]


def test_partial_publication_retains_identity_and_cannot_retry(full_verification):
    api, registry = full_verification
    proof = promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)
    expected = promotion.sha(promotion.canonical(proof))
    with (
        patch("scripts.promotion.verify", return_value=proof),
        patch.object(api, "write", side_effect=OSError("uncertain tag response")),
        pytest.raises(OSError),
    ):
        promotion.publish(
            api, registry, inputs(), release.ROOT, expected, REPO + "/actions/runs/10"
        )
    assert registry.stable == registry.image
    with pytest.raises(ValueError, match="already exists"):
        promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)


def registry_image():
    media = "application/vnd.oci.image.manifest.v1+json"
    raw = (
        json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": media,
                "config": {"digest": DIGEST},
                "layers": [],
            },
            indent=3,
        ).encode()
        + b"\n"
    )
    return {
        "raw": raw,
        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "media": media,
    }


def test_registry_copy_preserves_every_manifest_byte_and_checks_published_digest():
    image = registry_image()
    registry = object.__new__(promotion.Registry)
    registry.tokens = {
        "application": "private-registry-token",
        "source-browser": "private-browser-token",
    }
    with (
        patch.object(registry, "lookup", side_effect=[None, image]),
        patch(
            "scripts.promotion.open_request",
            return_value=Response(
                b"", status=201, headers={"Docker-Content-Digest": image["digest"]}
            ),
        ) as request,
    ):
        registry.copy(image, "v0.1.0")
    sent = request.call_args.args[0]
    assert sent.method == "PUT"
    assert sent.full_url == "https://ghcr.io/v2/jshauns81/librarium/manifests/0.1.0"
    assert sent.data is image["raw"]
    assert sent.get_header("Content-type") == image["media"]


def test_registry_lookup_validates_bytes_without_repackaging():
    image = registry_image()
    with patch(
        "scripts.promotion.open_request",
        side_effect=[
            Response(b'{"token":"private"}'),
            Response(b'{"token":"private-browser"}'),
            Response(
                image["raw"],
                headers={
                    "Docker-Content-Digest": image["digest"],
                    "Content-Type": image["media"],
                },
            ),
        ],
    ) as request:
        registry = promotion.Registry("secret", "owner", push=True)
        assert registry.lookup("v0.1.0-beta.2") == image
    assert "pull%2Cpush" in request.call_args_list[0].args[0].full_url


@pytest.mark.parametrize("status", [301, 302, 307, 401, 403, 429, 500])
def test_registry_refuses_transport_errors_instead_of_claiming_absence(status):
    registry = object.__new__(promotion.Registry)
    registry.tokens = {"application": "private", "source-browser": "private-browser"}
    error = urllib.error.HTTPError(
        "https://ghcr.io", status, "refused", {}, io.BytesIO()
    )
    with (
        patch("scripts.promotion.open_request", side_effect=error),
        pytest.raises(urllib.error.HTTPError),
    ):
        registry.lookup("v0.1.0")


def test_registry_rejects_indexes_or_changed_bytes_and_destination_races():
    registry = object.__new__(promotion.Registry)
    registry.tokens = {"application": "private", "source-browser": "private-browser"}
    image = registry_image()
    with (
        patch(
            "scripts.promotion.open_request",
            return_value=Response(
                image["raw"] + b" ",
                headers={
                    "Docker-Content-Digest": image["digest"],
                    "Content-Type": image["media"],
                },
            ),
        ),
        pytest.raises(ValueError),
    ):
        registry.lookup("v0.1.0-beta.2")
    raw = b'{"schemaVersion":2,"manifests":[]}'
    with (
        patch(
            "scripts.promotion.open_request",
            return_value=Response(
                raw,
                headers={
                    "Docker-Content-Digest": "sha256:"
                    + hashlib.sha256(raw).hexdigest(),
                    "Content-Type": "application/vnd.oci.image.index.v1+json",
                },
            ),
        ),
        pytest.raises(ValueError),
    ):
        registry.lookup("v0.1.0-beta.2")
    with (
        patch.object(registry, "lookup", return_value=image),
        patch("scripts.promotion.open_request") as request,
        pytest.raises(ValueError),
    ):
        registry.copy(image, "v0.1.0")
    request.assert_not_called()


def test_symlinked_compatibility_source_cannot_escape_pinned_checkout(
    full_verification, tmp_path
):
    api, registry = full_verification
    folder = tmp_path / "backend/librarium"
    folder.mkdir(parents=True)
    (folder / "migrations").mkdir()
    (folder / "epub_inspection.py").symlink_to(
        release.ROOT / "backend/librarium/epub_inspection.py"
    )
    with pytest.raises(ValueError, match="escaped checkout"):
        promotion.verify(api, registry, inputs(), tmp_path, now=NOW)
    assert api.writes == registry.writes == []


def test_legacy_python_input_validation_avoids_parsing_accepted_source():
    python = Path("/usr/bin/python3")
    if not python.is_file():
        pytest.skip("system Python unavailable")
    env = os.environ | {
        "GITHUB_REPOSITORY": promotion.REPO,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
    }
    args = [str(python), str(release.ROOT / "scripts/promotion.py"), "validate-inputs"]
    for key, value in inputs().__dict__.items():
        args.append("--" + key.replace("_", "-") + "=" + value)
    result = subprocess.run(args, env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    env["GITHUB_REF"] = "refs/heads/feature"
    result = subprocess.run(args, env=env, text=True, capture_output=True, check=False)
    assert result.returncode != 0 and "Promotion refused" in result.stderr
    assert "manual and main-only" in result.stderr


def test_asset_same_size_changed_bytes_are_refused():
    with (
        patch("scripts.promotion.open_request", return_value=Response()),
        pytest.raises(ValueError),
    ):
        promotion.GitHub("private").asset(
            {"id": 12, "size": 2, "digest": "sha256:" + "a" * 64}
        )


def test_cli_transport_failure_hides_remote_details(monkeypatch, tmp_path, capsys):
    argv = ["promotion.py", "verify"]
    for key, value in inputs().__dict__.items():
        argv.append("--" + key.replace("_", "-") + "=" + value)
    argv += ["--source-root=.", "--output=" + str(tmp_path / "proof.json")]
    monkeypatch.setattr("sys.argv", argv)
    for name, value in {
        "GITHUB_REPOSITORY": promotion.REPO,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GH_TOKEN": "synthetic-private-credential",
        "GITHUB_ACTOR": "jshauns81",
    }.items():
        monkeypatch.setenv(name, value)
    error = urllib.error.HTTPError(
        "https://example.invalid/?signed=synthetic-sensitive-location",
        403,
        "synthetic-sensitive-reason",
        {},
        io.BytesIO(),
    )
    with (
        patch("scripts.promotion.Registry", side_effect=error),
        pytest.raises(SystemExit),
    ):
        promotion.main()
    error.close()
    stderr = capsys.readouterr().err
    assert "HTTPError" in stderr
    assert "synthetic-" not in stderr
    assert not (tmp_path / "proof.json").exists()


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "different_digest",
        "different_config",
        "different_pin",
        "occupied_stable",
    ],
)
def test_browser_pair_mismatch_refuses_before_any_writes(full_verification, change):
    api, registry = full_verification
    if change == "missing":
        registry.browser = None
    elif change == "different_digest":
        registry.browser["digest"] = "sha256:" + "c" * 64
    elif change == "different_config":
        registry.browser["raw"] = b'{"config":{"digest":"sha256:bad"}}'
    elif change == "different_pin":
        original = registry.lookup
        registry.lookup = lambda ref, role="application": (
            None if ref == BROWSER_DIGEST else original(ref, role)
        )
    else:
        registry.browser_stable = registry.browser
    with pytest.raises(ValueError):
        promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)
    assert api.writes == registry.writes == []


@pytest.mark.parametrize("change", ["missing", "changed", "duplicate"])
def test_install_archive_is_required_and_bound_to_source(full_verification, change):
    api, registry = full_verification
    if change == "missing":
        api.beta["assets"].pop()
    elif change == "changed":
        api.stack_raw += b"changed"
    else:
        api.beta["assets"].append(api.stack_metadata)
    with pytest.raises(ValueError):
        promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)
    assert api.writes == registry.writes == []


def test_second_registry_copy_failure_never_creates_git_tag_or_release(
    full_verification,
):
    api, registry = full_verification
    proof = promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)
    expected = promotion.sha(promotion.canonical(proof))
    original = registry.copy

    def fail_browser(image, destination, role="application"):
        if role == "source-browser":
            raise OSError("uncertain registry response")
        original(image, destination, role)

    with (
        patch("scripts.promotion.verify", return_value=proof),
        patch.object(registry, "copy", side_effect=fail_browser),
        pytest.raises(OSError),
    ):
        promotion.publish(
            api, registry, inputs(), release.ROOT, expected, REPO + "/actions/runs/10"
        )
    assert api.writes == []
    assert registry.stable is not None
    with pytest.raises(ValueError, match="already exists"):
        promotion.verify(api, registry, inputs(), release.ROOT, now=NOW)


def test_browser_registry_scope_requests_and_exact_copy_are_separate():
    image = registry_image()
    with patch(
        "scripts.promotion.open_request",
        side_effect=[
            Response(b'{"token":"application-token"}'),
            Response(b'{"token":"browser-token"}'),
        ],
    ) as request:
        registry = promotion.Registry("secret", "owner", push=True)
    from urllib.parse import parse_qs, urlsplit

    assert [
        parse_qs(urlsplit(call.args[0].full_url).query)["scope"]
        for call in request.call_args_list
    ] == [
        ["repository:jshauns81/librarium:pull,push"],
        ["repository:jshauns81/librarium-source-browser:pull,push"],
    ]
    with (
        patch.object(registry, "lookup", side_effect=[None, image]),
        patch(
            "scripts.promotion.open_request",
            return_value=Response(
                b"", status=201, headers={"Docker-Content-Digest": image["digest"]}
            ),
        ) as request,
    ):
        registry.copy(image, "v0.1.0", "source-browser")
    sent = request.call_args.args[0]
    assert (
        sent.full_url
        == "https://ghcr.io/v2/jshauns81/librarium-source-browser/manifests/0.1.0"
    )
    assert sent.get_header("Authorization") == "Bearer browser-token"
    assert sent.data == image["raw"]
