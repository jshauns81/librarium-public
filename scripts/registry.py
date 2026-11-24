"""Query only the Librarium GHCR manifest, without following credential redirects."""

import argparse
import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.request

REPOSITORIES = {
    "application": "jshauns81/librarium",
    "source-browser": "jshauns81/librarium-source-browser",
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url: str, authorization: str):
    opener = urllib.request.build_opener(NoRedirect)
    return opener.open(
        urllib.request.Request(
            url,
            headers={
                "Authorization": authorization,
                "Accept": "application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json",
            },
        ),
        timeout=30,
    )


def lookup(
    version: str, credential: str, actor: str, *, role: str = "application"
) -> tuple[str, dict] | None:
    if not re.fullmatch(
        r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)-beta\.[1-9][0-9]*",
        version,
    ):
        raise ValueError("invalid beta version")
    repository = REPOSITORIES[role]
    basic = base64.b64encode(f"{actor}:{credential}".encode()).decode()
    with request(
        "https://ghcr.io/token?service=ghcr.io&scope=repository:"
        + repository
        + ":pull",
        "Basic " + basic,
    ) as response:
        token = json.load(response)["token"]
    try:
        with request(
            "https://ghcr.io/v2/" + repository + "/manifests/" + version[1:],
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["absent", "digest"])
    parser.add_argument("version")
    parser.add_argument("--role", choices=REPOSITORIES, default="application")
    args = parser.parse_args()
    try:
        if args.command == "absent":
            for role in REPOSITORIES:
                if (
                    lookup(
                        args.version,
                        os.environ["GH_TOKEN"],
                        os.environ["GITHUB_ACTOR"],
                        role=role,
                    )
                    is not None
                ):
                    raise ValueError("version already exists; use a new beta number")
        else:
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
    except (ValueError, KeyError, urllib.error.URLError) as exc:
        # Do not print URLs, headers or credentials from transport exceptions.
        parser.exit(1, f"Registry check refused: {type(exc).__name__}\n")


if __name__ == "__main__":
    main()
