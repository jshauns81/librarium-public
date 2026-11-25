"""Stage a privately reviewed beta image pair in private GHCR packages."""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import urllib.error
from pathlib import Path

if __package__:
    from . import registry, release
else:
    import registry
    import release

SOURCE = "https://github.com/" + release.REPOSITORY


def copy_reviewed(source, target, expected):
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("invalid reviewed archive hash")
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("archive must be a regular file")
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as original, target.open("xb") as copy:
            while chunk := original.read(1024 * 1024):
                digest.update(chunk)
                copy.write(chunk)
        if digest.hexdigest() != expected:
            target.unlink()
            raise ValueError("archive hash mismatch")
    finally:
        os.close(fd)


def check_config(raw, expected):
    if len(raw) > 1024 * 1024 or "sha256:" + hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("image configuration digest mismatch")
    config = json.loads(raw)
    if config.get("config", {}).get("Labels", {}).get("org.opencontainers.image.source") != SOURCE:
        raise ValueError("image source label mismatch")


def run_skopeo(args, *, input_data=None, policy=None):
    env = dict(os.environ)
    env.pop("GH_TOKEN", None)
    env.pop("GITHUB_TOKEN", None)
    command = ["skopeo"]
    if policy is not None:
        command += ["--policy", str(policy)]
    return subprocess.run(
        command + args, input=input_data, env=env, check=True, capture_output=True
    ).stdout


class Stager:
    def __init__(self, credential, actor, authfile, policy=None):
        self.credential = credential
        self.actor = actor
        self.authfile = authfile
        self.policy = policy
        self.absent_packages = set()

    def api(self, path):
        return registry.request(
            "https://api.github.com" + path,
            "Bearer " + self.credential,
            accept="application/vnd.github+json",
        )

    def preflight(self, version, commit):
        owner = release.REPOSITORY.split("/")[0]
        with self.api("/user") as response:
            user = json.load(response)
            scopes = {
                scope.strip() for scope in response.headers.get("X-OAuth-Scopes", "").split(",")
            }
        if user.get("login") != owner or self.actor != owner or "write:packages" not in scopes:
            raise ValueError("authenticated owner and package scopes required")
        # An authenticated owner package-list response establishes that a missing
        # package lookup is not merely an anonymous visibility response.
        with self.api("/user/packages?package_type=container&per_page=1") as response:
            if not isinstance(json.load(response), list):
                raise TypeError("owner package access required")
        for role, repository in registry.REPOSITORIES.items():
            package = repository.split("/")[1]
            try:
                with self.api(f"/users/{owner}/packages/container/{package}") as response:
                    metadata = json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
                exc.close()
                self.absent_packages.add(role)
                continue
            if not registry.private_container(metadata, owner, package):
                raise ValueError("private owner package required")
            for ref in (version, "sha-" + commit):
                if registry.lookup(ref, self.credential, self.actor, role=role) is not None:
                    raise ValueError("version or source tag already exists")

    def push(self, role, archive, version, commit, receipt):
        image = release.IMAGES[role]
        tag = version[1:]
        if role not in self.absent_packages:
            for ref in (version, "sha-" + commit):
                if registry.lookup(ref, self.credential, self.actor, role=role) is not None:
                    raise ValueError("version or source tag already exists")
        run_skopeo(
            [
                "copy",
                "--authfile",
                str(self.authfile),
                "docker-archive:" + str(archive),
                f"docker://{image}:{tag}",
            ],
            policy=self.policy,
        )
        # Confirm privacy and config identity immediately after the first write.
        owner, package = registry.REPOSITORIES[role].split("/")
        with self.api(f"/users/{owner}/packages/container/{package}") as response:
            metadata = json.load(response)
        if not registry.private_container(metadata, owner, package):
            raise ValueError("staged package is not private")
        found = registry.lookup(version, self.credential, self.actor, role=role)
        if found is None or found[1].get("config", {}).get("digest") != receipt[role]:
            raise ValueError("staged image differs from accepted image")
        if registry.lookup("sha-" + commit, self.credential, self.actor, role=role) is not None:
            raise ValueError("source tag already exists")
        run_skopeo(
            [
                "copy",
                "--preserve-digests",
                "--authfile",
                str(self.authfile),
                f"docker://{image}@{found[0]}",
                f"docker://{image}:sha-{commit}",
            ],
            policy=self.policy,
        )


def publish_pair(client, archives, version, commit, receipt):
    client.preflight(version, commit)
    for role in ("application", "source-browser"):
        client.push(role, archives[role], version, commit, receipt)
    return registry.verify_private_pair(version, commit, receipt, client.credential, client.actor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    for role in ("application", "source-browser"):
        parser.add_argument("--" + role + "-archive", required=True, type=Path)
        parser.add_argument("--" + role + "-sha256", required=True)
    args = parser.parse_args()
    try:
        release.validate(args.version, args.commit)
        receipt = json.loads(args.receipt.read_bytes())
        release.verify_images(receipt, args.commit, receipt["application"])
        credential, actor = os.environ["GH_TOKEN"], os.environ["GITHUB_ACTOR"]
        if not credential or not actor:
            raise ValueError("credentials required")
        with tempfile.TemporaryDirectory(prefix="librarium-stage-") as temp:
            root = Path(temp)
            archives = {}
            for role in ("application", "source-browser"):
                key = role.replace("-", "_")
                archive = root / (role + ".tar.gz")
                copy_reviewed(
                    getattr(args, key + "_archive"), archive, getattr(args, key + "_sha256")
                )
                archives[role] = archive
                check_config(
                    run_skopeo(["inspect", "--raw", "--config", "docker-archive:" + str(archive)]),
                    receipt[role],
                )
            authfile = root / "auth.json"
            policy = root / "policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "default": [{"type": "reject"}],
                        "transports": {
                            "docker-archive": {"": [{"type": "insecureAcceptAnything"}]},
                            "docker": {
                                "ghcr.io/" + repo: [{"type": "insecureAcceptAnything"}]
                                for repo in registry.REPOSITORIES.values()
                            },
                        },
                    }
                )
            )
            run_skopeo(
                [
                    "login",
                    "--authfile",
                    str(authfile),
                    "--username",
                    actor,
                    "--password-stdin",
                    "ghcr.io",
                ],
                input_data=(credential + "\n").encode(),
            )
            digests = publish_pair(
                Stager(credential, actor, authfile, policy),
                archives,
                args.version,
                args.commit,
                receipt,
            )
            print(json.dumps(digests, sort_keys=True))
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        urllib.error.URLError,
        subprocess.SubprocessError,
    ):
        parser.exit(1, "Private staging refused; inspect local inputs and package state.\n")


if __name__ == "__main__":
    main()
