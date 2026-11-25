"""Query only the Librarium GHCR manifest, without following credential redirects."""

import argparse
import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

if __package__:
    from . import release
else:
    import release

REPOSITORIES = {role: image.removeprefix("ghcr.io/") for role, image in release.IMAGES.items()}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(
    url: str,
    authorization: str,
    *,
    accept: str = "application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json",
):
    opener = urllib.request.build_opener(NoRedirect)
    return opener.open(
        urllib.request.Request(
            url,
            headers={
                "Authorization": authorization,
                "Accept": accept,
            },
        ),
        timeout=30,
    )


def lookup(
    version: str, credential: str, actor: str, *, role: str = "application"
) -> tuple[str, dict] | None:
    if re.fullmatch(release.BETA, version):
        tag = version[1:]
    elif re.fullmatch(r"sha-[0-9a-f]{40}", version):
        tag = version
    else:
        raise ValueError("invalid beta or source tag")
    repository = REPOSITORIES[role]
    basic = base64.b64encode(f"{actor}:{credential}".encode()).decode()
    with request(
        "https://ghcr.io/token?service=ghcr.io&scope=repository:" + repository + ":pull",
        "Basic " + basic,
    ) as response:
        token = json.load(response)["token"]
    try:
        with request(
            "https://ghcr.io/v2/" + repository + "/manifests/" + tag,
            "Bearer " + token,
        ) as response:
            raw = response.read(1024 * 1024 + 1)
            digest = response.headers["Docker-Content-Digest"]
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code == 404:
            return None
        raise
    if len(raw) > 1024 * 1024 or digest != "sha256:" + hashlib.sha256(raw).hexdigest():
        raise ValueError("registry manifest digest mismatch")
    return digest, json.loads(raw)


def private_container(metadata: dict, owner: str, package: str) -> bool:
    return (
        metadata.get("visibility") == "private"
        and metadata.get("name") == package
        and isinstance(metadata.get("owner"), dict)
        and metadata["owner"].get("login") == owner
        and metadata.get("package_type") == "container"
    )


def verify_private_pair(
    version: str, commit: str, receipt: dict, credential: str, actor: str
) -> dict:
    release.validate(version, commit)
    release.verify_images(receipt, commit, receipt["application"])
    digests = {}
    for role, repository in REPOSITORIES.items():
        owner, package = repository.split("/")
        with request(
            f"https://api.github.com/users/{owner}/packages/container/{package}",
            "Bearer " + credential,
            accept="application/vnd.github+json",
        ) as response:
            metadata = json.load(response)
        if not private_container(metadata, owner, package):
            raise ValueError("private package identity required")
        tagged = lookup(version, credential, actor, role=role)
        source = lookup("sha-" + commit, credential, actor, role=role)
        if tagged is None or tagged != source or tagged[1]["config"]["digest"] != receipt[role]:
            raise ValueError("staged tags or accepted image identity differ")
        digests[role] = tagged[0]
    return digests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["absent", "digest", "verify-pair"])
    parser.add_argument("version")
    parser.add_argument("--commit", help="reviewed source SHA for an absence check")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--role", choices=REPOSITORIES, default="application")
    args = parser.parse_args()
    try:
        if args.command == "verify-pair":
            if not args.receipt:
                raise ValueError("missing accepted image receipt")
            digests = verify_private_pair(
                args.version,
                args.commit or "",
                json.loads(args.receipt.read_bytes()),
                os.environ["GH_TOKEN"],
                os.environ["GITHUB_ACTOR"],
            )
            print(json.dumps(digests, sort_keys=True))
        elif args.command == "absent":
            release.validate(args.version, args.commit or "")
            for role in REPOSITORIES:
                for reference in (args.version, "sha-" + args.commit):
                    if lookup(
                        reference, os.environ["GH_TOKEN"], os.environ["GITHUB_ACTOR"], role=role
                    ):
                        raise ValueError("version or source tag already exists")
        else:
            if not re.fullmatch(release.BETA, args.version):
                raise ValueError("invalid beta version")
            found = lookup(
                args.version,
                os.environ["GH_TOKEN"],
                os.environ["GITHUB_ACTOR"],
                role=args.role,
            )
            if found is None:
                raise ValueError("published manifest missing")
            expected = os.environ.get("EXPECTED_IMAGE_ID")
            if not expected or found[1].get("config", {}).get("digest") != expected:
                raise ValueError("published image differs from accepted image")
            print(found[0])
    except (ValueError, KeyError, TypeError, OSError, urllib.error.URLError) as exc:
        # Do not print URLs, headers or credentials from transport exceptions.
        parser.exit(1, f"Registry check refused: {type(exc).__name__}\n")


if __name__ == "__main__":
    main()
