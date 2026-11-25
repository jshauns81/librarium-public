"""Verify beta acceptance and promote its exact existing manifest without a build."""

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

if __package__:
    from . import release
    from .registry import NoRedirect, private_container
else:
    import release
    from registry import NoRedirect, private_container

REPO = release.REPOSITORY
WEB = "https://github.com/" + REPO
API = "https://api.github.com/repos/" + REPO
OWNER_ID = 57206355
DIGEST = r"sha256:[0-9a-f]{64}"
STABLE = rf"v{release.NUMBER}\.{release.NUMBER}\.{release.NUMBER}"
MEDIA = {
    "application/vnd.docker.distribution.manifest.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
}
MAX_JSON = 1024 * 1024


class Refusal(ValueError):
    """A policy guard with a fixed, safe operator-facing reason."""


def require(condition, message):
    if not condition:
        raise Refusal(message)


def positive(value):
    require(type(value) is int and value > 0, "expected positive integer")
    return value


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("non-finite JSON number")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def timestamp(value):
    require(
        type(value) is str
        and re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value
        ),
        "expected UTC timestamp",
    )
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


@dataclass(frozen=True)
class Inputs:
    beta: str
    source: str
    digest: str
    browser_digest: str
    stable: str
    issue: str
    comment: str
    confirmation: str

    def __post_init__(self):
        require(
            all(type(getattr(self, key)) is str for key in self.__dataclass_fields__),
            "promotion inputs must be strings",
        )
        release.validate(self.beta, self.source)
        require(
            all(
                re.fullmatch(DIGEST, value)
                for value in (self.digest, self.browser_digest)
            ),
            "expected immutable image digest",
        )
        require(
            re.fullmatch(STABLE, self.stable)
            and self.beta.startswith(self.stable + "-beta."),
            "stable version must match beta release line",
        )
        require(
            self.confirmation == "PROMOTE", "explicit PROMOTE confirmation required"
        )
        for value in [self.issue, self.comment]:
            require(
                type(value) is str and re.fullmatch(r"[1-9][0-9]{0,19}", value),
                "expected numeric issue and comment IDs",
            )


def open_request(request):
    return urllib.request.build_opener(NoRedirect).open(request, timeout=30)


def bounded(response, limit=MAX_JSON):
    raw = response.read(limit + 1)
    require(len(raw) <= limit, "response exceeds budget")
    return raw


class GitHub:
    def __init__(self, token):
        self.token = token

    def request(
        self,
        path,
        method="GET",
        data=None,
        accept="application/vnd.github+json",
        upload=False,
    ):
        require(
            path.startswith("/")
            and not path.startswith("//")
            and not any(x in path for x in ["#", "\\", ":"]),
            "invalid fixed-repository API path",
        )
        base = "https://uploads.github.com/repos/" + REPO if upload else API
        headers = {
            "Authorization": "Bearer " + self.token,
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "librarium-promotion",
        }
        if data is not None:
            headers["Content-Type"] = (
                "application/octet-stream" if upload else "application/json"
            )
        return urllib.request.Request(
            base + path, data=data, headers=headers, method=method
        )

    def get(self, path, missing=False):
        try:
            with open_request(self.request(path)) as response:
                require(response.status == 200, "unexpected GitHub response")
                return strict_json(bounded(response))
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code == 404 and missing:
                return None
            raise

    def write(self, path, data, method="POST", upload=False):
        raw = data if type(data) is bytes else canonical(data)
        with open_request(self.request(path, method, raw, upload=upload)) as response:
            require(response.status in [200, 201], "unexpected GitHub write response")
            return strict_json(bounded(response))

    def asset(self, metadata):
        asset_id = positive(metadata["id"])
        size = positive(metadata["size"])
        require(
            size <= 65536 and re.fullmatch(DIGEST, metadata["digest"]),
            "invalid release asset metadata",
        )
        try:
            response = open_request(
                self.request(
                    f"/releases/assets/{asset_id}", accept="application/octet-stream"
                )
            )
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location", "")
            status = exc.code
            exc.close()
            require(status == 302, "asset download refused")
            target = urllib.parse.urlsplit(location)
            require(
                len(location) <= 8192
                and target.scheme == "https"
                and target.netloc == "release-assets.githubusercontent.com"
                and target.path.startswith("/")
                and not target.fragment,
                "untrusted asset redirect",
            )
            # Signed download receives neither API authorization nor cookies.
            response = open_request(
                urllib.request.Request(
                    location, headers={"Accept": "application/octet-stream"}
                )
            )
        with response:
            require(response.status == 200, "unexpected asset response")
            raw = bounded(response, 65536)
        require(
            len(raw) == size and "sha256:" + sha(raw) == metadata["digest"],
            "release asset bytes changed",
        )
        return raw


def comment_proof(comment, issue, number):
    require(positive(comment["id"]) == number, "comment identity changed")
    require(
        comment["issue_url"] == API + f"/issues/{issue}",
        "comment belongs to another issue",
    )
    require(
        comment["html_url"] == WEB + f"/issues/{issue}#issuecomment-{number}",
        "comment URL mismatch",
    )
    require(
        type(comment["body"]) is str and len(comment["body"].encode()) <= 65536,
        "invalid evidence body",
    )
    return {
        "url": comment["html_url"],
        "body_sha256": sha(comment["body"].encode()),
        "author": {key: comment["user"][key] for key in ["login", "id", "type"]},
        "created_at": comment["created_at"],
        "updated_at": comment["updated_at"],
    }


def acceptance_record(api, args, published, now):
    comment = api.get(f"/issues/comments/{args.comment}")
    proof = comment_proof(comment, int(args.issue), int(args.comment))
    require(
        proof["author"] == {"login": REPO.split("/")[0], "id": OWNER_ID, "type": "User"}
        and comment["author_association"] == "OWNER",
        "acceptance requires repository owner attestation",
    )
    require(
        comment["created_at"] == comment["updated_at"],
        "edited acceptance cannot authorize promotion",
    )
    created = timestamp(comment["created_at"])
    require(
        timestamp(published) <= created <= now,
        "acceptance timestamp outside beta period",
    )
    data = strict_json(comment["body"])
    require(
        type(data) is dict
        and set(data)
        == {
            "schema",
            "repository",
            "beta",
            "source_sha",
            "image_digest",
            "source_browser_digest",
            "observation",
            "representative_session",
            "restart_reconnect",
            "blocking_defects",
        },
        "invalid beta acceptance schema",
    )
    require(
        data["schema"] == "librarium.beta-acceptance.v2"
        and data["repository"] == WEB
        and data["beta"] == args.beta
        and data["source_sha"] == args.source
        and data["image_digest"] == args.digest
        and data["source_browser_digest"] == args.browser_digest,
        "acceptance does not bind selected beta",
    )
    window = data["observation"]
    require(
        type(window) is dict and set(window) == {"started_at", "ended_at"},
        "invalid observation window",
    )
    start, end = timestamp(window["started_at"]), timestamp(window["ended_at"])
    require(
        timestamp(published) <= start <= end <= created
        and end - start >= timedelta(hours=48),
        "48-hour beta observation incomplete",
    )
    require(
        data["blocking_defects"] == [] and type(data["blocking_defects"]) is list,
        "unresolved blocking defects",
    )
    evidence = {}
    for key in ["representative_session", "restart_reconnect"]:
        verdict = data[key]
        require(
            type(verdict) is dict
            and set(verdict) == {"complete", "evidence"}
            and verdict["complete"] is True,
            "required beta journey not accepted",
        )
        require(
            type(verdict["evidence"]) is list and 1 <= len(verdict["evidence"]) <= 8,
            "required beta journey evidence absent",
        )
        for url in verdict["evidence"]:
            require(type(url) is str, "invalid evidence URL")
            match = re.fullmatch(
                re.escape(WEB)
                + r"/issues/([1-9][0-9]{0,19})#issuecomment-([1-9][0-9]{0,19})",
                url,
            )
            require(
                match is not None, "evidence must be a same-repository issue comment"
            )
            issue, number = map(int, match.groups())
            require(
                number != int(args.comment),
                "acceptance cannot be its own journey evidence",
            )
            item = api.get(f"/issues/comments/{number}")
            captured = comment_proof(item, issue, number)
            require(
                timestamp(published)
                <= timestamp(item["created_at"])
                <= timestamp(item["updated_at"])
                <= created,
                "journey evidence outside acceptance period",
            )
            evidence[url] = captured
    return proof | {
        "record": data,
        "evidence": [evidence[url] for url in sorted(evidence)],
    }


class Registry:
    def __init__(self, credential, actor, push=False):
        self.credential = credential
        basic = base64.b64encode(f"{actor}:{credential}".encode()).decode()
        self.tokens = {}
        for role, image in release.IMAGES.items():
            scope = (
                "repository:"
                + image.removeprefix("ghcr.io/")
                + (":pull,push" if push else ":pull")
            )
            url = "https://ghcr.io/token?" + urllib.parse.urlencode(
                {"service": "ghcr.io", "scope": scope}
            )
            with open_request(
                urllib.request.Request(url, headers={"Authorization": "Basic " + basic})
            ) as response:
                require(response.status == 200, "registry authentication failed")
                token = strict_json(bounded(response))["token"]
            require(
                type(token) is str and 0 < len(token) <= 16384,
                "invalid registry authorization",
            )
            self.tokens[role] = token

    def require_private(self):
        for image in release.IMAGES.values():
            owner, package = image.removeprefix("ghcr.io/").split("/")
            url = f"https://api.github.com/users/{owner}/packages/container/{package}"
            request = urllib.request.Request(
                url,
                headers={
                    "Authorization": "Bearer " + self.credential,
                    "Accept": "application/vnd.github+json",
                },
            )
            with open_request(request) as response:
                require(response.status == 200, "package visibility unavailable")
                metadata = strict_json(bounded(response))
            require(
                private_container(metadata, owner, package),
                "private package identity required",
            )

    def request(self, reference, data=None, media=None, role="application"):
        require(
            type(reference) is str
            and (
                re.fullmatch(DIGEST, reference)
                or re.fullmatch(STABLE, reference)
                or re.fullmatch(release.BETA, reference)
            ),
            "invalid registry reference",
        )
        reference = reference.removeprefix("v")
        headers = {
            "Authorization": "Bearer " + self.tokens[role],
            "Accept": ", ".join(sorted(MEDIA)),
        }
        if data is not None:
            require(media in MEDIA, "unsupported image manifest")
            headers["Content-Type"] = media
        return urllib.request.Request(
            "https://ghcr.io/v2/"
            + release.IMAGES[role].removeprefix("ghcr.io/")
            + "/manifests/"
            + reference,
            headers=headers,
            data=data,
            method="PUT" if data is not None else "GET",
        )

    def lookup(self, reference, role="application"):
        try:
            with open_request(self.request(reference, role=role)) as response:
                require(response.status == 200, "unexpected registry response")
                raw = bounded(response)
                digest = response.headers.get("Docker-Content-Digest")
                media = response.headers.get("Content-Type", "").split(";")[0]
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code == 404:
                return None
            raise
        require(
            digest == "sha256:" + sha(raw) and media in MEDIA,
            "registry manifest identity mismatch",
        )
        image = strict_json(raw)
        require(
            image.get("schemaVersion") == 2
            and image.get("mediaType") == media
            and "manifests" not in image
            and re.fullmatch(DIGEST, image.get("config", {}).get("digest", "")),
            "single image manifest required",
        )
        return {"raw": raw, "digest": digest, "media": media}

    def copy(self, source, destination, role="application"):
        require(
            self.lookup(destination, role) is None,
            "stable registry version already exists",
        )
        with open_request(
            self.request(destination, source["raw"], source["media"], role)
        ) as response:
            require(
                response.status == 201
                and response.headers.get("Docker-Content-Digest") == source["digest"],
                "registry publication identity mismatch",
            )
            bounded(response)
        require(
            self.lookup(destination, role) == source,
            "stable registry bytes differ from accepted beta",
        )


def stable_absent(api, registry, stable):
    require(
        api.get("/releases/tags/" + stable, missing=True) is None,
        "stable GitHub Release already exists",
    )
    require(
        api.get("/git/ref/tags/" + stable, missing=True) is None,
        "stable Git tag already exists",
    )
    for role in release.IMAGES:
        require(
            registry.lookup(stable, role) is None,
            "stable registry version already exists",
        )


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, timeout=30
    ).strip()


def successful_step(steps, name):
    found = [step for step in steps if step["name"] == name]
    return (
        len(found) == 1
        and found[0]["status"] == "completed"
        and found[0]["conclusion"] == "success"
    )


def beta_run(
    api,
    args,
    url,
    *,
    phase="rehearsal",
    rehearsal_id=None,
    rehearsal_attempt=None,
    stack_sha=None,
):
    match = re.fullmatch(re.escape(WEB) + r"/actions/runs/([1-9][0-9]*)", url)
    require(match is not None, "invalid beta workflow run URL")
    run_id = int(match[1])
    require(phase in {"rehearsal", "finalization"}, "invalid beta run phase")
    if phase == "finalization":
        require(
            type(rehearsal_id) is str
            and re.fullmatch(r"[1-9][0-9]*", rehearsal_id)
            and type(rehearsal_attempt) is int
            and rehearsal_attempt > 0
            and type(stack_sha) is str
            and re.fullmatch(r"[0-9a-f]{64}", stack_sha),
            "finalization rehearsal binding missing",
        )
        title = f"Finalize {args.beta} from {args.source} rehearsal {rehearsal_id} attempt {rehearsal_attempt} stack {stack_sha}"
    else:
        title = f"Rehearse {args.beta} from {args.source}"
    run = api.get(f"/actions/runs/{run_id}")
    positive(run["id"])
    positive(run["workflow_id"])
    require(
        run["id"] == run_id
        and run["html_url"] == url
        and run["path"] == ".github/workflows/beta.yml"
        and run["event"] == "workflow_dispatch"
        and run["head_branch"] == "main"
        and run["head_sha"] == args.source
        and run["display_title"] == title
        and run["repository"]["full_name"] == REPO
        and run["head_repository"]["full_name"] == REPO
        and run["status"] == "completed"
        and run["conclusion"] == "success",
        "beta workflow provenance or result refused",
    )
    attempt = positive(run["run_attempt"])
    response = api.get(f"/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")
    jobs = response["jobs"]
    require(
        type(jobs) is list
        and len(jobs) == response["total_count"]
        and len(jobs) <= 100,
        "incomplete workflow job evidence",
    )
    required = (
        {
            "validate",
            "quality / source-quality",
            "acceptance / candidate-container",
            "acceptance / populated-upgrade",
            "acceptance / container",
            "rehearsal",
        }
        if phase == "rehearsal"
        else {"validate", "publish"}
    )
    require(phase in {"rehearsal", "finalization"}, "invalid beta run phase")
    names = [job["name"] for job in jobs]
    require(
        len(names) == len(set(names)) and required <= set(names),
        "required beta jobs missing",
    )
    require(
        not any(
            job["name"] == ("publish" if phase == "rehearsal" else "rehearsal")
            and job["conclusion"] == "success"
            for job in jobs
        ),
        "beta run phase cannot be interchanged",
    )
    captured = []
    required_steps = {
        "rehearsal": [
            "Validate paired image identity and release assets before publication",
            "Retain release preflight assets",
        ],
        "publish": [
            "Verify rehearsal provenance and staged private image pair",
            "Publish the accepted image pair and immutable release record",
        ],
        "acceptance / candidate-container": [
            "Validate and build",
            "Capture tested image identity",
            "Validate registry-only configuration",
            "Start isolated stack",
            "Require kernel sandbox support in the actual image",
            "Check actual packaged application",
            "Prove native reference production without provider access in the actual image",
            "Verify state survives container replacement",
            "Inspect a preserved synthetic EPUB through the optional persistent file role",
            "Prove native read-only library access without Index in the actual image",
            "Exercise database and artifact backup/restore in disposable state",
            "Prove cover source network and capability isolation",
            "Prove composed runtime startup and fresh-cluster recovery",
            "Retain candidate runtime-startup proof",
            "Upgrade the local accepted candidate",
            "Copy portable proof for artifact upload",
            "Retain portable synthetic proof only",
            "Retain encrypted accepted images",
            "Source browser isolation and Chromium sandbox",
            "Export the accepted source browser",
        ],
        "acceptance / populated-upgrade": [
            "Select populated-upgrade tier",
            "Verify proof binds the accepted source and image",
        ],
        "acceptance / container": [
            "Require selected acceptance and report deferred tiers",
        ],
    }
    quality_profiles = [
        [
            "Frozen Python dependencies",
            "Frozen frontend dependencies",
            "Isolated native inputs",
            "Warning-strict Python tests",
            "Python types",
            "Python lint",
            "Migration, lock, export and workspace integrity",
            "Frontend tests",
            "Frontend types and build",
            "Frontend format",
            "Python dependency security audit",
            "Frontend dependency security audit",
            "Scan source history for secrets with redacted evidence",
        ],
    ]
    for job in jobs:
        positive(job["id"])
        positive(job["run_id"])
        positive(job["run_attempt"])
        require(
            job["run_id"] == run_id
            and job["run_attempt"] == attempt
            and job["status"] == "completed"
            and (
                job["conclusion"] == "success"
                if job["name"] in required
                else job["conclusion"] in {"success", "skipped"}
            ),
            "beta job not successful",
        )
        if job["name"] not in required:
            continue
        steps = job["steps"]
        require(
            type(steps) is list and len(steps) <= 100, "invalid workflow step evidence"
        )
        if job["name"] == "quality / source-quality":
            require(
                all(
                    successful_step(steps, name)
                    for name in (
                        "Check public content without exposing matched values",
                        "Record exact source and workflow provenance",
                    )
                ),
                "public source quality evidence missing or skipped",
            )
            require(
                any(
                    all(successful_step(steps, name) for name in profile)
                    for profile in quality_profiles
                ),
                "source quality profile missing or skipped",
            )
        for name in required_steps.get(job["name"], []):
            require(
                successful_step(steps, name),
                "packaged acceptance step missing or skipped",
            )
        captured.append(
            {
                "id": job["id"],
                "name": job["name"],
                "run_attempt": attempt,
                "conclusion": job["conclusion"],
                "steps": [
                    {k: step[k] for k in ["name", "status", "conclusion"]}
                    for step in steps
                ],
            }
        )
    return {
        key: run[key]
        for key in [
            "id",
            "html_url",
            "head_sha",
            "display_title",
            "run_attempt",
            "workflow_id",
            "path",
            "event",
            "head_branch",
            "status",
            "conclusion",
        ]
    } | {"jobs": sorted(captured, key=lambda job: job["name"])}


def rehearsal_evidence(
    api, version, source, url, manifest, receipt, archive, approved_sha
):
    release.validate(version, source)
    require(
        re.fullmatch(r"[0-9a-f]{64}", approved_sha) is not None,
        "reviewed stack digest required",
    )
    image_id = receipt["application"]
    browser_id = release.verify_images(receipt, source, image_id)
    expected = release.manifest(
        version,
        source,
        image_id,
        url,
        browser_digest=browser_id,
        image_id=image_id,
        browser_image_id=browser_id,
    )
    require(manifest == expected, "rehearsal manifest differs from source or version")
    require(
        archive == release.stack_archive() and sha(archive) == approved_sha,
        "reviewed stack archive differs from source or rehearsal",
    )
    return beta_run(
        api, SimpleNamespace(source=source, beta=version), url, phase="rehearsal"
    )


def verify(api, registry, args, source_root, now=None):
    now = now or datetime.now(UTC)
    require(
        git(source_root, "rev-parse", "HEAD") == args.source,
        "source checkout differs from requested source",
    )
    require(
        not git(source_root, "status", "--porcelain", "--untracked-files=all"),
        "source compatibility requires a clean checkout",
    )
    compatibility_paths = [
        source_root / "backend/librarium/epub_inspection.py",
        source_root / "backend/librarium/epubcheck_process.py",
    ]
    migrations = source_root / "backend/librarium/migrations"
    compatibility_paths.extend(migrations.glob("[0-9]*.py"))
    for path in [migrations, *compatibility_paths]:
        require(
            path.resolve().is_relative_to(source_root.resolve()),
            "compatibility source escaped checkout",
        )
        require(
            not any(
                item.is_symlink()
                for item in [path, *path.parents]
                if item != source_root.parent
            ),
            "compatibility source cannot use symlinks",
        )
        require(
            path.is_dir() if path == migrations else stat.S_ISREG(path.lstat().st_mode),
            "compatibility source must be regular",
        )
    subprocess.run(
        [
            "git",
            "-C",
            str(release.ROOT),
            "merge-base",
            "--is-ancestor",
            args.source,
            "origin/main",
        ],
        check=True,
        timeout=30,
        capture_output=True,
    )
    beta = api.get("/releases/tags/" + args.beta)
    positive(beta["id"])
    require(
        beta["tag_name"] == args.beta
        and beta["draft"] is False
        and beta["prerelease"] is True
        and beta["html_url"] == WEB + "/releases/tag/" + args.beta,
        "published beta prerelease required",
    )
    timestamp(beta["published_at"])
    require(
        type(beta["body"]) is str and 0 < len(beta["body"].encode()) <= 32768,
        "reviewed beta release notes required",
    )
    tag = api.get("/git/ref/tags/" + args.beta)
    require(
        tag["ref"] == "refs/tags/" + args.beta
        and tag["object"]["type"] == "tag"
        and re.fullmatch(r"[0-9a-f]{40}", tag["object"]["sha"]),
        "annotated beta Git tag required",
    )
    annotated = api.get("/git/tags/" + tag["object"]["sha"])
    require(
        annotated["tag"] == args.beta
        and annotated["object"]
        == {
            "type": "commit",
            "sha": args.source,
            "url": API + "/git/commits/" + args.source,
        },
        "beta Git tag source mismatch",
    )
    assets = [
        asset for asset in beta["assets"] if asset["name"] == "release-manifest.json"
    ]
    require(
        len(assets) == 1 and assets[0]["state"] == "uploaded",
        "one complete beta manifest asset required",
    )
    raw = api.asset(assets[0])
    manifest = strict_json(raw)
    require(
        manifest.get("schema") == "librarium.release.v2"
        and isinstance(manifest.get("images"), dict)
        and {"application", "source-browser"} <= set(manifest["images"]),
        "paired-image release manifest required; single-image releases cannot be promoted",
    )
    expected = release.manifest(
        args.beta,
        args.source,
        args.digest,
        manifest["acceptance"]["run"],
        browser_digest=args.browser_digest,
        image_id=manifest["images"]["application"]["config_digest"],
        browser_image_id=manifest["images"]["source-browser"]["config_digest"],
        root=source_root,
    )
    finalization_url = manifest["acceptance"].get("finalization_run")
    rehearsal_attempt = positive(manifest["acceptance"].get("rehearsal_attempt"))
    expected["acceptance"]["rehearsal_attempt"] = rehearsal_attempt
    expected["acceptance"]["finalization_run"] = finalization_url
    require(
        manifest == expected and finalization_url != manifest["acceptance"]["run"],
        "beta manifest differs from source compatibility or identity",
    )
    run = beta_run(api, args, manifest["acceptance"]["run"], phase="rehearsal")
    require(run["run_attempt"] == rehearsal_attempt, "rehearsal attempt changed")
    finalization = beta_run(
        api,
        args,
        finalization_url,
        phase="finalization",
        rehearsal_id=str(run["id"]),
        rehearsal_attempt=rehearsal_attempt,
        stack_sha=manifest["stack_assets"]["sha256"],
    )
    accepted = acceptance_record(api, args, beta["published_at"], now)
    stack_assets = [
        asset for asset in beta["assets"] if asset["name"] == "stack-assets.zip"
    ]
    require(
        len(stack_assets) == 1 and stack_assets[0]["state"] == "uploaded",
        "one complete stack asset required",
    )
    stack_raw = api.asset(stack_assets[0])
    require(
        stack_raw == release.stack_archive(source_root),
        "beta stack assets differ from source",
    )
    registry.require_private()
    for role, digest in (
        ("application", args.digest),
        ("source-browser", args.browser_digest),
    ):
        image = registry.lookup(args.beta, role)
        require(
            image is not None and image["digest"] == digest,
            "beta registry digest changed",
        )
        require(
            registry.lookup(digest, role) == image,
            "beta registry tag differs from immutable digest",
        )
        require(
            strict_json(image["raw"])["config"]["digest"]
            == manifest["images"][role]["config_digest"],
            "registry config differs from accepted image",
        )
    latest = api.get("/releases/latest", missing=True)
    previous = None
    if latest is not None:
        previous = latest["tag_name"]
        require(
            re.fullmatch(STABLE, previous)
            and latest["draft"] is False
            and latest["prerelease"] is False
            and tuple(map(int, previous[1:].split(".")))
            < tuple(map(int, args.stable[1:].split("."))),
            "stable version does not advance current stable",
        )
    stable_absent(api, registry, args.stable)
    return {
        "schema": "librarium.promotion-proof.v1",
        "beta": args.beta,
        "stable": args.stable,
        "source": args.source,
        "digest": args.digest,
        "source_browser_digest": args.browser_digest,
        "previous_supported_release": previous,
        "beta_release": {
            key: beta[key] for key in ["id", "html_url", "published_at", "updated_at"]
        },
        "beta_notes": beta["body"],
        "beta_notes_sha256": sha(beta["body"].encode()),
        "beta_manifest_digest": "sha256:" + sha(raw),
        "beta_manifest_asset": {
            key: assets[0][key]
            for key in ["id", "name", "size", "digest", "updated_at"]
        },
        "stack_asset": {
            key: stack_assets[0][key]
            for key in ["id", "name", "size", "digest", "updated_at"]
        },
        "beta_tag": {"object_sha": tag["object"]["sha"], "source_sha": args.source},
        "beta_run": run,
        "beta_finalization_run": finalization,
        "beta_acceptance": accepted,
        "manifest": manifest,
    }


def publish(api, registry, args, source_root, expected_proof, run_url):
    require(
        re.fullmatch(r"[0-9a-f]{64}", expected_proof), "invalid verified proof hash"
    )
    require(
        re.fullmatch(re.escape(WEB) + r"/actions/runs/[1-9][0-9]*", run_url),
        "invalid promotion run URL",
    )
    proof = verify(api, registry, args, source_root)
    require(
        sha(canonical(proof)) == expected_proof, "beta evidence changed since preflight"
    )
    manifest = copy_stable_manifest(proof, run_url, expected_proof)
    raw = json.dumps(manifest, indent=2).encode() + b"\n"
    images = {}
    for role, digest in (
        ("application", args.digest),
        ("source-browser", args.browser_digest),
    ):
        image = registry.lookup(digest, role)
        require(
            image is not None and image["digest"] == digest,
            "accepted manifest unavailable",
        )
        images[role] = image
    stack_raw = release.stack_archive(source_root)
    require(
        sha(stack_raw) == manifest["stack_assets"]["sha256"],
        "stack assets changed since preflight",
    )
    stable_absent(api, registry, args.stable)
    # Registry writes cannot transact across repositories; no Git release until both verify.
    for role, image in images.items():
        registry.copy(image, args.stable, role)
    require(
        all(
            registry.lookup(args.stable, role) == image
            for role, image in images.items()
        ),
        "stable image pair incomplete",
    )
    tag = api.write(
        "/git/tags",
        {
            "tag": args.stable,
            "message": f"Promoted {args.beta}; {args.digest}; {args.browser_digest}; proof {expected_proof}",
            "object": args.source,
            "type": "commit",
        },
    )
    api.write("/git/refs", {"ref": "refs/tags/" + args.stable, "sha": tag["sha"]})
    notes = (
        f"Promoted {args.beta} without rebuilding.\n\nImage: `{release.IMAGE}@{args.digest}`\n\nSource browser: `{release.IMAGES['source-browser']}@{args.browser_digest}`\n\nSource: `{args.source}`\n\nBeta: {proof['beta_release']['html_url']}\n\nAcceptance: {proof['beta_acceptance']['url']}\n\nBeta checks: {proof['beta_run']['html_url']}\n\nPromotion: {run_url}\n\nRead-only release; no library writer. Target activation is a separate approved operation. File inspection requires target kernel acceptance.\n\nSee the attached manifest for source-derived compatibility, supported previous release and acceptance provenance. Upgrade/recovery: {WEB}/blob/{args.source}/docs/releases.md#environment-isolation-and-activation\n\n## Candidate changes and limits recorded with {args.beta}\n\n"
        + proof["beta_notes"]
    )
    stable = api.write(
        "/releases",
        {
            "tag_name": args.stable,
            "target_commitish": args.source,
            "name": "Librarium " + args.stable,
            "draft": True,
            "prerelease": False,
            "body": notes,
        },
    )
    release_id = positive(stable["id"])
    for name, payload in (
        ("release-manifest.json", raw),
        ("stack-assets.zip", stack_raw),
    ):
        asset = api.write(
            f"/releases/{release_id}/assets?name={name}", payload, upload=True
        )
        require(
            asset["state"] == "uploaded"
            and asset["size"] == len(payload)
            and asset["digest"] == "sha256:" + sha(payload),
            "stable release asset mismatch",
        )
    registry.require_private()
    result = api.write(
        f"/releases/{release_id}",
        {"draft": False, "prerelease": False, "make_latest": "true"},
        method="PATCH",
    )
    require(
        result["tag_name"] == args.stable
        and result["draft"] is False
        and result["prerelease"] is False,
        "stable release publication incomplete",
    )
    final_tag = api.get("/git/ref/tags/" + args.stable)
    require(
        final_tag["object"]["type"] == "tag"
        and final_tag["object"]["sha"] == tag["sha"],
        "published stable Git tag changed",
    )
    final_object = api.get("/git/tags/" + tag["sha"])
    require(
        final_object["tag"] == args.stable
        and final_object["object"]["type"] == "commit"
        and final_object["object"]["sha"] == args.source,
        "published stable Git tag source mismatch",
    )
    final_release = api.get("/releases/tags/" + args.stable)
    require(
        final_release["id"] == release_id
        and final_release["tag_name"] == args.stable
        and final_release["draft"] is False
        and final_release["prerelease"] is False,
        "published stable Release mismatch",
    )
    for name, payload in (
        ("release-manifest.json", raw),
        ("stack-assets.zip", stack_raw),
    ):
        final_assets = [
            asset for asset in final_release["assets"] if asset["name"] == name
        ]
        require(
            len(final_assets) == 1 and api.asset(final_assets[0]) == payload,
            "published stable asset changed",
        )
    require(
        all(
            registry.lookup(args.stable, role) == image
            for role, image in images.items()
        )
        and api.get("/releases/latest")["id"] == release_id,
        "final stable image pair or latest release differs",
    )
    return manifest


def copy_stable_manifest(proof, run_url, proof_sha):
    manifest = dict(proof["manifest"])
    manifest.update(
        version=proof["stable"],
        channel="stable",
        previous_supported_release=proof["previous_supported_release"],
    )
    manifest["known_limits"] = [
        "Read-only release; no library writer",
        "File role requires target kernel acceptance",
        "Target activation requires separate concrete approval",
    ]
    manifest["promotion"] = {
        "beta": proof["beta"],
        "beta_release": proof["beta_release"]["html_url"],
        "beta_manifest_digest": proof["beta_manifest_digest"],
        "beta_notes_sha256": proof["beta_notes_sha256"],
        "beta_run": proof["beta_run"],
        "beta_finalization_run": proof["beta_finalization_run"],
        "beta_acceptance": proof["beta_acceptance"],
        "proof_sha256": proof_sha,
        "run": run_url,
    }
    return manifest


def rehearsal_main():
    parser = argparse.ArgumentParser(description="Verify a prior beta rehearsal")
    parser.add_argument("--version", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--stack", required=True, type=Path)
    parser.add_argument("--stack-sha256", required=True)
    args = parser.parse_args(sys.argv[2:])
    try:
        require(
            os.environ.get("GITHUB_REPOSITORY") == REPO
            and os.environ.get("GITHUB_REF") == "refs/heads/main"
            and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch",
            "rehearsal verification is manual and main-only",
        )
        require(
            re.fullmatch(r"[1-9][0-9]*", args.run_id) is not None,
            "invalid rehearsal run ID",
        )
        url = WEB + "/actions/runs/" + args.run_id
        proof = rehearsal_evidence(
            GitHub(os.environ["GH_TOKEN"]),
            args.version,
            args.source,
            url,
            strict_json(args.manifest.read_bytes()),
            strict_json(args.receipt.read_bytes()),
            args.stack.read_bytes(),
            args.stack_sha256,
        )
        require(
            re.fullmatch(r"[1-9][0-9]*", args.attempt) is not None
            and int(args.attempt) == proof["run_attempt"],
            "rehearsal attempt changed during verification",
        )
        print(json.dumps({"run": url, "attempt": proof["run_attempt"]}))
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        reason = str(exc) if isinstance(exc, Refusal) else type(exc).__name__
        parser.exit(1, f"Rehearsal refused: {reason}\n")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "verify-rehearsal":
        rehearsal_main()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate-inputs", "verify", "publish"])
    for name in [
        "beta",
        "source",
        "digest",
        "browser_digest",
        "stable",
        "issue",
        "comment",
        "confirmation",
    ]:
        parser.add_argument("--" + name.replace("_", "-"), required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-proof")
    args = parser.parse_args()
    try:
        selected = Inputs(
            **{key: getattr(args, key) for key in Inputs.__dataclass_fields__}
        )
        require(
            os.environ.get("GITHUB_REPOSITORY") == REPO
            and os.environ.get("GITHUB_REF") == "refs/heads/main"
            and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch",
            "promotion is manual and main-only",
        )
        if args.command == "validate-inputs":
            return
        require(
            args.output is not None
            and not args.output.exists()
            and args.source_root is not None,
            "exclusive output and source checkout required",
        )
        api = GitHub(os.environ["GH_TOKEN"])
        registry = Registry(
            os.environ["GH_TOKEN"],
            os.environ["GITHUB_ACTOR"],
            push=args.command == "publish",
        )
        if args.command == "verify":
            result = verify(api, registry, selected, args.source_root)
            print(sha(canonical(result)))
        else:
            run_url = (
                WEB + "/actions/runs/" + str(positive(int(os.environ["GITHUB_RUN_ID"])))
            )
            result = publish(
                api,
                registry,
                selected,
                args.source_root,
                args.expected_proof or "",
                run_url,
            )
        with args.output.open("x") as target:
            target.write(json.dumps(result, indent=2) + "\n")
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        # Transport errors may contain credentials or signed download locations.
        reason = str(exc) if isinstance(exc, Refusal) else type(exc).__name__
        parser.exit(
            1,
            f"Promotion refused: {reason}; inspect any partial identities before retrying.\n",
        )


if __name__ == "__main__":
    main()
