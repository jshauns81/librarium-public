"""Disposable sanitized historical-source/schema upgrade acceptance; never activation."""

import argparse
import fnmatch
import hashlib
import json
import os
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
from librarium.build_identity import compatibility, constant

from scripts.capture_source import git, safe_path

BASELINE = "bf7af4d0042d452bfc7d288b92046861f63c2743"
BASELINE_TREE = "6cfc1a5c9554629f84a504bfed6ca3ef13165e8b"
POSTGRES_IMAGE = (
    "postgres:18.6-bookworm@sha256:bbf83594798e144bff365a9c191c5d779f181fb3135902064ab8ff11918020fc"
)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


class CommandFailure(RuntimeError):
    def __init__(self, stderr):
        super().__init__("rehearsal_command_failed")
        self.stderr = stderr


def image_inventory(source, root):
    patterns = [
        line.strip().strip("/")
        for line in (root / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    require(not any(p.startswith("!") for p in patterns), "unsupported_dockerignore")
    included, excluded = {}, []
    for name, value in source["files"].items():
        if not name.startswith("backend/"):
            continue
        parts = name.split("/")
        prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
        if any(fnmatch.fnmatchcase(prefix, pattern) for prefix in prefixes for pattern in patterns):
            excluded.append(name)
        else:
            included[name.removeprefix("backend/")] = value["sha256"]
    return included, sorted(excluded)


def migration_failure_proof(stderr, applied):
    require(
        b'relation "librarium_correctedepub" already exists' in stderr,
        "unexpected_migration_failure",
    )
    require(
        any(name.startswith("0007_") for name in applied)
        and not any(int(name[:4]) >= 8 for name in applied),
        "unexpected_migration_failure_prefix",
    )


def loss_boundary(old, current, pre, post, old_ids):
    require(
        not {row["id"] for row in current["rows"]} & set(old_ids),
        "post_upgrade_jobs_in_old_restore",
    )
    return {
        "jobs": [
            {
                "id": row["id"],
                "request_key": row["request_key"],
                "result_sha256": digest(encoded(row["result"])),
            }
            for row in current["rows"]
        ],
        "artifacts": {
            name: value
            for name, value in post["artifacts"]["files"].items()
            if name not in pre["artifacts"]["files"]
        },
        "pending_transition": {"before": old["pending"], "after": current["pending_after"]},
    }


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def write_json(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
    path.chmod(0o600)


def check_baseline_policy(value):
    if value != {
        "migration_leaves": ["0005_epub_validation_jobs"],
        "inspection_policy": "librarium.epub-structure.v5",
        "validation_policy": "librarium.epub-validation.v1",
    }:
        raise ValueError("baseline_policy_mismatch")


def source_policy(root):
    migrations = {}
    import ast

    for path in (root / "backend/librarium/migrations").glob("[0-9]*.py"):
        tree = ast.parse(path.read_text())
        migration = next(
            n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Migration"
        )
        deps = next(
            n.value
            for n in migration.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "dependencies" for t in n.targets)
        )
        migrations[path.stem] = ast.literal_eval(deps)
    depended = {name for deps in migrations.values() for app, name in deps if app == "librarium"}
    return {
        "migration_leaves": sorted(set(migrations) - depended),
        "inspection_policy": constant(
            "backend/librarium/epub_inspection.py", "POLICY_VERSION", root=root
        ),
        "validation_policy": constant(
            "backend/librarium/epubcheck_process.py", "VALIDATION_POLICY", "version", root=root
        ),
    }


def export_source(repo, ref, target, *, baseline=False, expected_tree=BASELINE_TREE):
    commit = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    tree = git(repo, "rev-parse", f"{commit}^{{tree}}").decode().strip()
    if baseline and (commit != BASELINE or tree != BASELINE_TREE or tree != expected_tree):
        raise ValueError("baseline_source_tree_mismatch")
    entries = []
    # Reuse the capture owner's path/mode boundaries, including files needed by Docker.
    for entry in git(repo, "ls-tree", "-r", "-z", commit).split(b"\0"):
        if not entry:
            continue
        meta, raw = entry.split(b"\t", 1)
        name = safe_path(raw.decode())
        mode, kind, blob = meta.decode().split()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError("source_link_or_mode")
        entries.append((name, mode, blob))
    target.mkdir(mode=0o700)
    files = {}
    for name, mode, blob in entries:
        data = git(repo, "cat-file", "blob", blob)
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o755 if mode == "100755" else 0o644)
        files[name] = {"sha256": digest(data), "mode": mode}
    policy = source_policy(target)
    if baseline:
        check_baseline_policy(policy)
    return {
        "commit": commit,
        "tree": tree,
        "files_sha256": digest(encoded(files)),
        "files": files,
        "policy": policy,
    }


def inventory(root):
    result = {}
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("artifact_root_mode")
    for path in sorted(root.iterdir()):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("artifact_type")
        result[path.name] = {
            "sha256": digest(path.read_bytes()),
            "size": info.st_size,
            "mode": stat.S_IMODE(info.st_mode),
            "uid": info.st_uid,
            "gid": info.st_gid,
        }
    return {
        "root": {"mode": 0o700, "uid": info_owner(root)[0], "gid": info_owner(root)[1]},
        "files": result,
    }


def info_owner(path):
    return path.stat().st_uid, path.stat().st_gid


def capture_files(dump, artifacts):
    if not dump.is_file() or dump.is_symlink() or not dump.stat().st_size:
        raise ValueError("database_capture_missing")
    return {"database_sha256": digest(dump.read_bytes()), "artifacts": inventory(artifacts)}


def verify_capture(value, dump, artifacts):
    if value != capture_files(dump, artifacts):
        raise ValueError("capture_integrity_mismatch")


class Supervision:
    """Orchestrator guard; the historical app itself has no new rollback guard."""

    def __init__(self):
        self.roles = {}
        self.current = False

    def start(self, role, generation):
        if generation == "old" and self.current:
            raise ValueError("image_only_rollback_unsupported")
        if generation == "current" and not self.current:
            if self.roles:
                raise ValueError("incompatible_worker_overlap")
            raise ValueError("current_not_migrated")
        if any(g != generation for g in self.roles.values()):
            raise ValueError("incompatible_worker_overlap")
        if role in self.roles:
            raise ValueError("role_already_running")
        self.roles[role] = generation

    def stop(self, role):
        del self.roles[role]

    def migrated(self):
        if self.roles:
            raise ValueError("roles_must_be_stopped")
        self.current = True

    def capture(self):
        if self.roles:
            raise ValueError("capture_requires_stopped_roles")


class Runner:
    def __init__(self, stage, docker=False, pg_bin=None):
        self.stage, self.docker, self.pg_bin = stage, docker, pg_bin
        self.name = "librarium-upgrade-" + secrets.token_hex(6)
        self.containers = []
        self.processes = []
        self.lifecycle = []
        self.network = False
        self.cluster = False
        self.socket_directory = None
        self.images = {}
        self.old_image_built = False
        self.password = secrets.token_urlsafe(48)
        self.env = {
            k: v
            for k, v in os.environ.items()
            if k
            in {
                "PATH",
                "HOME",
                "LANG",
                "LD_LIBRARY_PATH",
                "LIBARCHIVE",
                "LIBRARIUM_EPUBCHECK_DIR",
                "LIBRARIUM_JAVA",
            }
        }
        self.env.update(
            POSTGRES_PASSWORD=self.password,
            PGUSER="librarium",
            PGPORT="55439",
            PGPASSWORD=self.password,
            LIBRARIUM_SECRET_KEY=secrets.token_urlsafe(60),
            DJANGO_SETTINGS_MODULE="librarium.settings",
            LIBRARIUM_UPGRADE_FIXTURE="1",
            PYTHONDONTWRITEBYTECODE="1",
            LIBRARIUM_PUBLIC_ORIGIN="",
        )
        self.supervision = Supervision()
        self.states = {"upgrade": self.supervision}
        self.runtime_env = {}

    def run(self, args, *, env=None, cwd=None, data=None, timeout=240):
        result = subprocess.run(
            [str(x) for x in args],
            input=data,
            capture_output=True,
            check=False,
            env=env or self.env,
            cwd=cwd,
            timeout=timeout,
        )
        if result.returncode:
            # Native commands may include configured values; retain only synthetic logs privately.
            with (self.stage / "failure.log").open("ab") as log:
                log.write(result.stdout + result.stderr)
            raise CommandFailure(result.stderr)
        return result.stdout

    def database_start(self):
        if self.docker:
            self.run(["docker", "network", "create", "--internal", self.name])
            self.network = True
            name = self.name + "-db"
            self.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    name,
                    "--network",
                    self.name,
                    "-e",
                    "POSTGRES_USER=librarium",
                    "-e",
                    "POSTGRES_PASSWORD",
                    POSTGRES_IMAGE,
                ]
            )
            self.containers.append(name)
            self.env.update(PGHOST=name, PGPORT="5432")
        else:
            self.socket_directory = tempfile.TemporaryDirectory(prefix="librarium-upgrade-socket-")
            socket = Path(self.socket_directory.name)
            self.env["PGHOST"] = str(socket)
            self.run(
                [
                    self.pg_bin / "initdb",
                    "-D",
                    self.stage / "postgres",
                    "--auth=trust",
                    "-U",
                    "librarium",
                ]
            )
            self.cluster = True
            self.run(
                [
                    self.pg_bin / "pg_ctl",
                    "-D",
                    self.stage / "postgres",
                    "-l",
                    self.stage / "postgres.log",
                    "-o",
                    f"-k {socket} -p 55439 -h ''",
                    "-w",
                    "start",
                ]
            )
            self.cluster = True
        deadline = time.monotonic() + 60
        while True:
            try:
                version = (
                    self.db("psql", "-d", "postgres", "-Atc", "show server_version_num")
                    .decode()
                    .strip()
                )
                require(version.startswith("18"), "server/client_major_mismatch")
                require(b"18." in self.db("pg_dump", "--version"), "server/client_major_mismatch")
                break
            except RuntimeError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
        self.server_version = version
        self.db("createdb", "upgrade")

    def db(self, command, *args, data=None):
        prefix = (
            [
                "docker",
                "exec",
                "-i",
                "-e",
                "PGPASSWORD",
                self.name + "-db",
                command,
            ]
            if self.docker
            else [self.pg_bin / command]
        )
        if self.docker and args != ("--version",):
            prefix += ["-h", "127.0.0.1", "-U", "librarium"]
        return self.run([*prefix, *args], data=data)

    def verify_schema(self, database, source):
        names = (
            self.db(
                "psql",
                "-d",
                database,
                "-Atc",
                "SELECT name FROM django_migrations WHERE app='librarium' ORDER BY name",
            )
            .decode()
            .splitlines()
        )
        expected = sorted(
            Path(name).stem
            for name in source["files"]
            if name.startswith("backend/librarium/migrations/")
            and Path(name).name[:4].isdigit()
            and name.endswith(".py")
        )
        require(names == expected, "applied_schema_mismatch")
        leaf = source["policy"]["migration_leaves"]
        if leaf in (
            ["0015_cover_search"],
            ["0016_source_browser_page"],
            ["0017_cover_source_timings"],
        ):
            columns = (
                self.db(
                    "psql",
                    "-d",
                    database,
                    "-Atc",
                    "SELECT column_name FROM information_schema.columns WHERE table_schema='public' "
                    "AND table_name='librarium_coversearch' ORDER BY column_name",
                )
                .decode()
                .splitlines()
            )
            require(
                set(columns)
                == {
                    "id",
                    "request_key",
                    "entry_id",
                    "actor",
                    "request",
                    "binding",
                    "query",
                    "sources",
                    "image_url",
                    "statuses",
                    "candidates",
                    "state",
                    "lease_token",
                    "lease_until",
                    "attempts",
                    "created_at",
                }
                | ({"source_timings"} if leaf == ["0017_cover_source_timings"] else set()),
                "cover_search_schema_mismatch",
            )

        if leaf in (["0016_source_browser_page"], ["0017_cover_source_timings"]):
            columns = (
                self.db(
                    "psql",
                    "-d",
                    database,
                    "-Atc",
                    "SELECT column_name FROM information_schema.columns WHERE table_schema='public' "
                    "AND table_name='librarium_sourcebrowserpage' ORDER BY column_name",
                )
                .decode()
                .splitlines()
            )
            require(
                set(columns) == {"query_key", "html", "url", "checked_at"},
                "browser_cache_schema_mismatch",
            )

    def verify_cover_runtime(self, database):
        accepted = (
            self.db(
                "psql",
                "-d",
                database,
                "-Atc",
                "SELECT bool_and(has_table_privilege('upgrade_runtime','public.' || t,p)) "
                "AND NOT bool_or(has_table_privilege('upgrade_runtime','public.' || t,d)) "
                "FROM unnest(ARRAY['librarium_coversearch','librarium_sourcebrowserpage']) t "
                "CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) p "
                "CROSS JOIN unnest(ARRAY['TRUNCATE','REFERENCES','TRIGGER']) d",
            )
            .decode()
            .strip()
        )
        require(accepted == "t", "cover_search_runtime_grants_mismatch")

    def app_command(self, generation, database, artifacts, command):
        env = self.env | {"PGDATABASE": database}
        if generation == "current":
            env.update(self.runtime_env)
        if self.docker:
            args = [
                "docker",
                "run",
                "--rm",
                "--init",
                "--network",
                self.name,
                "--read-only",
                "--tmpfs",
                "/tmp:size=64m",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "-v",
                f"{artifacts}:/artifacts",
                "-v",
                f"{self.stage / 'receipts'}:/receipts",
                "-v",
                f"{self.stage / 'current/scripts/upgrade_fixture.py'}:/proof/upgrade_fixture.py:ro",
            ]
            for key in env:
                if key.startswith(("PG", "LIBRARIUM_SECRET", "LIBRARIUM_RUNTIME")) or key in {
                    "DJANGO_SETTINGS_MODULE",
                    "LIBRARIUM_PUBLIC_ORIGIN",
                    "LIBRARIUM_UPGRADE_FIXTURE",
                }:
                    args += ["-e", key]
            args += [
                "-e",
                "LIBRARIUM_ARTIFACT_DIR=/artifacts",
                "-e",
                "PYTHONPATH=/app/backend",
                self.images[generation],
                "python",
                *command,
            ]
            return args, env, None
        root = self.stage / generation
        env.update(PYTHONPATH=str(root / "backend"), LIBRARIUM_ARTIFACT_DIR=str(artifacts))
        return [root / ".venv/bin/python", *command], env, root / "backend"

    def app(self, generation, database, artifacts, *command, maintenance=False):
        state = self.states.setdefault(database, Supervision())
        if generation == "old" and state.current:
            raise ValueError("image_only_rollback_unsupported")
        if maintenance:
            state.capture()
        else:
            state.start("bounded-actor", generation)
        try:
            args, env, cwd = self.app_command(generation, database, artifacts, command)
            container = None
            if self.docker:
                container = self.name + "-actor-" + secrets.token_hex(4)
                args[2:2] = ["--name", container]
                self.containers.append(container)
            result = self.run(args, env=env, cwd=cwd)
            if container:
                self.containers.remove(container)
            self.lifecycle.append(
                {
                    "generation": generation,
                    "database": database,
                    "role": "bounded_actor",
                    "exited": True,
                }
            )
            return result
        finally:
            if not maintenance:
                state.stop("bounded-actor")

    def fixture(self, generation, database, artifacts, phase):
        script = (
            "/proof/upgrade_fixture.py"
            if self.docker
            else str(self.stage / "current/scripts/upgrade_fixture.py")
        )
        receipt = (
            "/receipts/fixture.json" if self.docker else str(self.stage / "receipts/fixture.json")
        )
        if database == "upgrade":
            self.supervision.start("fixture-worker", generation)
        try:
            return self.app(generation, database, artifacts, script, phase, "--receipt", receipt)
        finally:
            if database == "upgrade":
                self.supervision.stop("fixture-worker")

    def web(self, generation, database, artifacts):
        self.supervision.start("web", generation)
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        args, env, cwd = self.app_command(
            generation,
            database,
            artifacts,
            ["manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"],
        )
        container = self.name + "-web"
        if self.docker:
            args[2:2] = ["--name", container]
            self.containers.append(container)
        with (self.stage / "web.log").open("ab") as log:
            process = subprocess.Popen(args, env=env, cwd=cwd, stdout=log, stderr=log)
        self.processes.append(process)
        url = f"http://127.0.0.1:{port}/api/health"
        deadline = time.monotonic() + 45
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while True:
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("owned_web_failed")
            try:
                if self.docker:
                    body = self.run(
                        [
                            "docker",
                            "exec",
                            container,
                            "python",
                            "-c",
                            "import urllib.request; print(urllib.request.urlopen("
                            + repr(url)
                            + ",timeout=2).read().decode())",
                        ],
                        timeout=5,
                    )
                else:
                    with opener.open(url, timeout=2) as response:
                        body = response.read(4096)
                require(json.loads(body) == {"status": "ready"}, "web_not_ready")
                break
            except RuntimeError, urllib.error.URLError:
                time.sleep(0.1)
        if self.docker:
            self.run(["docker", "stop", "--time=10", container])
            self.containers.remove(container)
        else:
            process.terminate()
        process.wait(timeout=30)
        self.supervision.stop("web")
        self.lifecycle.append(
            {
                "generation": generation,
                "database": database,
                "role": "web",
                "health": "ready",
                "admission_stopped": True,
                "exited": True,
            }
        )

    def capture(self, database, artifacts, name):
        self.supervision.capture()
        root = self.stage / name
        root.mkdir(mode=0o700)
        dump = root / "postgres.dump"
        dump.write_bytes(self.db("pg_dump", "-d", database, "-Fc"))
        dump.chmod(0o600)
        shutil.copytree(artifacts, root / "artifacts", copy_function=shutil.copy2)
        if self.docker:
            os.chown(root / "artifacts", *info_owner(artifacts))
            for file in (root / "artifacts").iterdir():
                os.chown(file, *info_owner(artifacts / file.name))
        captured = datetime.now(UTC)
        manifest = capture_files(dump, root / "artifacts")
        require(inventory(artifacts) == manifest["artifacts"], "capture_incoherent")
        write_json(root / "capture.json", manifest)
        return root, manifest, captured

    def restore(self, capture, manifest, database, name):
        verify_capture(manifest, capture / "postgres.dump", capture / "artifacts")
        self.db("createdb", database)
        self.db(
            "pg_restore",
            "--exit-on-error",
            "--no-privileges",
            "-d",
            database,
            data=(capture / "postgres.dump").read_bytes(),
        )
        artifacts = self.stage / name
        shutil.copytree(capture / "artifacts", artifacts, copy_function=shutil.copy2)
        if self.docker:
            os.chown(artifacts, *info_owner(capture / "artifacts"))
            for file in artifacts.iterdir():
                os.chown(file, *info_owner(capture / "artifacts" / file.name))
        require(inventory(artifacts) == manifest["artifacts"], "restore_artifacts_changed")
        return artifacts

    def receipt(
        self, artifacts, database, scope, captured, started, completed, seconds, *, historical=False
    ):
        path = (
            ("/receipts/" if self.docker else str(self.stage / "receipts") + "/") + scope + ".json"
        )
        code = (
            "from datetime import datetime; from pathlib import Path; "
            "from librarium.recovery_evidence import identity_binding,make_receipt,retain_receipt; "
            "from librarium.build_identity import load_build_identity; "
            + ("identity=None; " if historical else "identity=load_build_identity(); ")
            + (
                "identity is not None or (_ for _ in ()).throw(ValueError('packaged_identity_missing')); "
                if self.docker and not historical
                else ""
            )
            + "retain_receipt(Path("
            + repr(path)
            + "),make_receipt("
            + repr(scope)
            + ",datetime.fromisoformat("
            + repr(captured.isoformat())
            + "),datetime.fromisoformat("
            + repr(started.isoformat())
            + "),datetime.fromisoformat("
            + repr(completed.isoformat())
            + "),"
            + repr(seconds)
            + ",identity_binding(identity)))"
        )
        self.app("current", database, artifacts, "-c", code)

    def close(self):
        outcomes = []

        def attempt(kind, action):
            try:
                action()
                outcomes.append({"resource": kind, "stopped": True})
            except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                outcomes.append({"resource": kind, "stopped": False, "error": type(exc).__name__})

        for container in reversed(self.containers):

            def remove_container(c=container):
                try:
                    self.run(["docker", "rm", "-f", "-v", c])
                except CommandFailure as exc:
                    if (
                        b"No such container" not in exc.stderr
                        and b"No such object" not in exc.stderr
                    ):
                        raise RuntimeError("owned_container_cleanup_failed") from None

            attempt("owned_container_and_anonymous_volumes", remove_container)
        for process in self.processes:

            def stop_process(p=process):
                if p.poll() is None:
                    p.terminate()
                    p.wait(timeout=30)

            attempt("owned_process", stop_process)
        if self.cluster:
            attempt(
                "owned_postgres_cluster",
                lambda: self.run(
                    [
                        self.pg_bin / "pg_ctl",
                        "-D",
                        self.stage / "postgres",
                        "-m",
                        "fast",
                        "-w",
                        "stop",
                    ]
                ),
            )
        if self.socket_directory is not None:
            attempt("owned_socket_directory", self.socket_directory.cleanup)
        if self.network:
            attempt("owned_network", lambda: self.run(["docker", "network", "rm", self.name]))
        if self.old_image_built:
            attempt(
                "owned_historical_image_tag",
                lambda: self.run(["docker", "image", "rm", self.name + "-old"]),
            )
        return {
            "scope": "exact_owned_disposable_cluster_processes_containers",
            "stopped": all(item["stopped"] for item in outcomes),
            "resources": outcomes,
            "retained": "Synthetic exports/captures/evidence; no real library inputs",
        }


def require_candidate_schema(policy):
    require(
        policy["migration_leaves"] == ["0017_cover_source_timings"], "candidate_schema_mismatch"
    )


def rehearse(args):
    stage = args.output.resolve()
    stage.mkdir(mode=0o700)  # Exclusive creation: never adopt existing state.
    runner = Runner(stage, args.mode == "image", args.pg_bin.resolve() if args.pg_bin else None)
    try:
        baseline = export_source(ROOT, BASELINE, stage / "old", baseline=True)
        candidate = export_source(ROOT, args.candidate, stage / "current")
        git(ROOT, "merge-base", "--is-ancestor", BASELINE, candidate["commit"])
        candidate["compatibility"] = compatibility(stage / "current")
        require_candidate_schema(candidate["policy"])
        for name in ("scripts/populated_upgrade.py", "scripts/upgrade_fixture.py"):
            require(
                (stage / "current" / name).read_bytes() == (ROOT / name).read_bytes(),
                "candidate_harness_mismatch",
            )
        receipts = stage / "receipts"
        receipts.mkdir(mode=0o700)
        artifacts = stage / "artifacts"
        artifacts.mkdir(mode=0o700)
        builds = {}
        if runner.docker:
            if os.geteuid() != 0:
                raise ValueError(
                    "image_mode_requires_disposable_runner_root_for_owner_verification"
                )
            os.chown(receipts, 10001, 10001)
            os.chown(artifacts, 10001, 10001)
            runner.run(
                [
                    "docker",
                    "build",
                    "--platform=linux/amd64",
                    "-t",
                    runner.name + "-old",
                    stage / "old",
                ],
                timeout=900,
            )
            runner.old_image_built = True
            for generation, image in [
                ("old", runner.name + "-old"),
                ("current", args.candidate_image),
            ]:
                if not image:
                    raise ValueError("exact_candidate_image_required")
                image_id = (
                    runner.run(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
                    .decode()
                    .strip()
                )
                if generation == "current" and image != image_id:
                    raise ValueError("candidate_image_requires_config_digest")
                runner.images[generation] = image_id
                builds[generation] = image_id
        else:
            if not args.pg_bin:
                raise ValueError("explicit_pg_bin_required")
            for generation in ("old", "current"):
                runner.run(
                    ["uv", "sync", "--project", stage / generation, "--frozen", "--no-dev"],
                    timeout=300,
                )
                builds[generation] = {
                    "python": runner.run([stage / generation / ".venv/bin/python", "--version"])
                    .decode()
                    .strip(),
                    "uv_lock_sha256": digest((stage / generation / "uv.lock").read_bytes()),
                }
        runner.database_start()
        # Check actual runtime files before migrations, including the affected image backend.
        for generation, source in [("old", baseline), ("current", candidate)]:
            expected, excluded = image_inventory(source, stage / generation)
            source["image_excluded_backend"] = excluded
            if not runner.docker:
                expected = {
                    name.removeprefix("backend/"): value["sha256"]
                    for name, value in source["files"].items()
                    if name.startswith("backend/")
                }
            code = (
                "import hashlib,pathlib\nexpected="
                + repr(expected)
                + "\nif not all(hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()==h for p,h in expected.items()):\n raise ValueError('runtime_source_mismatch')\n"
            )
            runner.app(generation, "upgrade", artifacts, "-c", code, maintenance=True)
        runner.app("old", "upgrade", artifacts, "manage.py", "migrate", "--noinput")
        runner.fixture("old", "upgrade", artifacts, "seed")
        runner.fixture("old", "upgrade", artifacts, "verify-old")
        runner.web("old", "upgrade", artifacts)
        pre, pre_manifest, captured = runner.capture("upgrade", artifacts, "pre-upgrade")
        # Failed migration in a separate clone must not admit current workers.
        failed_artifacts = runner.restore(pre, pre_manifest, "failed_migration", "failed-artifacts")
        runner.db(
            "psql",
            "-d",
            "failed_migration",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "CREATE TABLE librarium_correctedepub (id integer)",
        )
        try:
            runner.app(
                "current",
                "failed_migration",
                failed_artifacts,
                "manage.py",
                "migrate",
                "--noinput",
                maintenance=True,
            )
        except CommandFailure as exc:
            applied = (
                runner.db(
                    "psql",
                    "-d",
                    "failed_migration",
                    "-Atc",
                    "SELECT name FROM django_migrations WHERE app='librarium' ORDER BY name",
                )
                .decode()
                .splitlines()
            )
            migration_failure_proof(exc.stderr, applied)
        else:
            raise AssertionError("failed_migration_negative_did_not_fail")
        try:
            runner.app(
                "current",
                "failed_migration",
                failed_artifacts,
                "manage.py",
                "inspection_worker",
                "--once",
            )
        except ValueError as exc:
            require(str(exc) == "current_not_migrated", "unexpected_failed_migration_guard")
        else:
            raise AssertionError("failed_migration_admitted_worker")
        runner.app(
            "current", "upgrade", artifacts, "manage.py", "migrate", "--noinput", maintenance=True
        )
        runner.verify_schema("upgrade", candidate)
        runner.db(
            "psql",
            "-d",
            "upgrade",
            "-v",
            "ON_ERROR_STOP=1",
            data=(
                "CREATE ROLE upgrade_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '"
                + runner.password
                + "';"
            ).encode(),
        )
        runner.app(
            "current",
            "upgrade",
            artifacts,
            "manage.py",
            "provision_runtime_role",
            "upgrade_runtime",
            maintenance=True,
        )
        runner.verify_cover_runtime("upgrade")
        runner.runtime_env = {
            "LIBRARIUM_RUNTIME_DB_USER": "upgrade_runtime",
            "LIBRARIUM_RUNTIME_DB_PASSWORD": runner.password,
        }
        runner.supervision.migrated()
        runner.fixture("current", "upgrade", artifacts, "verify-current")
        runner.fixture("current", "upgrade", artifacts, "work-current")
        runner.web("current", "upgrade", artifacts)
        runner.fixture("current", "upgrade", artifacts, "verify-all")
        post, post_manifest, post_captured = runner.capture("upgrade", artifacts, "post-upgrade")
        started = datetime.now(UTC)
        recovery_clock = time.monotonic()
        post_artifacts = runner.restore(
            post, post_manifest, "current_restore", "current-restored-artifacts"
        )
        runner.verify_schema("current_restore", candidate)
        runner.states.setdefault("current_restore", Supervision()).migrated()
        runtime_env = runner.runtime_env
        runner.runtime_env = {}
        try:
            runner.app(
                "current",
                "current_restore",
                post_artifacts,
                "manage.py",
                "provision_runtime_role",
                "upgrade_runtime",
                maintenance=True,
            )
        finally:
            runner.runtime_env = runtime_env
        runner.verify_cover_runtime("current_restore")
        runner.fixture("current", "current_restore", post_artifacts, "verify-all")
        recovery_seconds = time.monotonic() - recovery_clock
        completed = datetime.now(UTC)
        runner.receipt(
            post_artifacts,
            "current_restore",
            "isolated_populated_upgrade",
            post_captured,
            started,
            completed,
            recovery_seconds,
        )
        old_started = datetime.now(UTC)
        old_clock = time.monotonic()
        old_artifacts = runner.restore(pre, pre_manifest, "old_restore", "old-restored-artifacts")
        runner.verify_schema("old_restore", baseline)
        runner.fixture("old", "old_restore", old_artifacts, "verify-old")
        old_seconds = time.monotonic() - old_clock
        old_completed = datetime.now(UTC)
        runner.receipt(
            old_artifacts,
            "current_restore",
            "isolated_pre_upgrade_generation",
            captured,
            old_started,
            old_completed,
            old_seconds,
            historical=True,
        )
        try:
            runner.app("old", "upgrade", artifacts, "manage.py", "check")
        except ValueError as exc:
            require(str(exc) == "image_only_rollback_unsupported", "unexpected_rollback_guard")
        else:
            raise AssertionError("rollback_negative_did_not_fail")
        result = {
            "schema": "librarium.populated-upgrade.v1",
            "outcome": "passed",
            "scope": "sanitized_historical_source_schema_fixture",
            "runtime": args.mode,
            "baseline": baseline,
            "candidate": candidate,
            "builds": builds,
            "postgres_version_num": runner.server_version,
            "lifecycle": runner.lifecycle,
            "pre_capture": pre_manifest,
            "post_capture": post_manifest,
            "fixture_sha256": digest((receipts / "fixture.json").read_bytes()),
            "current_fixture_sha256": digest((receipts / "current-fixture.json").read_bytes()),
            "harness_sha256": digest(Path(__file__).read_bytes()),
            "adapter_sha256": digest((stage / "current/scripts/upgrade_fixture.py").read_bytes()),
            "old_recovery": {
                "capture_age_seconds": (old_started - captured).total_seconds(),
                "recovery_seconds": old_seconds,
            },
            "current_recovery": {
                "capture_age_seconds": (started - post_captured).total_seconds(),
                "recovery_seconds": recovery_seconds,
            },
            "old_generation_loss": loss_boundary(
                json.loads((receipts / "fixture.json").read_text()),
                json.loads((receipts / "current-fixture.json").read_text()),
                pre_manifest,
                post_manifest,
                runner.db("psql", "-d", "old_restore", "-Atc", "SELECT id::text FROM librarium_job")
                .decode()
                .splitlines(),
            ),
            "target": {
                "state": "held",
                "running_image": None,
                "kernel": None,
                "storage": None,
                "custody": None,
                "capacity": None,
                "authentication_session": None,
                "human_observation_48h": None,
            },
            "assertions": [
                "old_runtime_completed",
                "historical_reads",
                "obsolete_pending_refused",
                "failed_migration_held",
                "no_incompatible_overlap",
                "image_only_rollback_refused",
                "pre_generation_reopened",
                "current_work_replacement_restore",
            ],
        }
    finally:
        active_error = sys.exc_info()[0] is not None
        cleanup = runner.close()
        try:
            write_json(stage / "cleanup.json", cleanup)
        except OSError:
            if not active_error:
                raise
            print("cleanup_receipt_write_failed", file=sys.stderr)
        if not cleanup["stopped"] and not active_error:
            raise RuntimeError("owned_cleanup_incomplete")
    write_json(stage / "result.json", result)
    print(
        "PASS: isolated populated sanitized historical-source/schema upgrade and both generations reopened"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["source", "image"], required=True)
    parser.add_argument("--candidate", default="HEAD")
    parser.add_argument("--candidate-image")
    parser.add_argument("--pg-bin", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rehearse(args)


if __name__ == "__main__":
    # Direct invocation supports project-owned imports without a global installation.
    main()
