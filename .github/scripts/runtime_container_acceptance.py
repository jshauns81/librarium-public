"""Run the deployed credential chain and fresh-cluster recovery on synthetic state."""

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

EPUB = ROOT / ".github/scripts/epub_container_acceptance.py"
REFERENCE = ROOT / ".github/scripts/reference_container_acceptance.py"
ROLE_CHECK = ROOT / "scripts/runtime_identity.py"


def require(value, message):
    if not value:
        raise RuntimeError(message)


def safe_diagnostics(data, environment):
    text = data.decode("utf-8", errors="replace")
    credentials = {
        value
        for key, value in environment.items()
        if value
        and any(part in key for part in ("PASSWORD", "SECRET", "TOKEN", "_KEY"))
    }
    for value in sorted(credentials, key=len, reverse=True):
        text = text.replace(value, "[REDACTED]")
    return text[-16384:]


def failure_phases(failure, provision, ready):
    def completed(state, success):
        return (
            state is not None
            and state["Status"] == "exited"
            and (state["ExitCode"] == 0) == success
        )

    if failure == "wrong_password":
        require(
            completed(provision, True), "password case did not reach runtime admission"
        )
        require(
            completed(ready, False), "incorrect password did not fail runtime admission"
        )
    else:
        require(completed(provision, False), "invalid provisioning was not refused")
        require(
            ready is None or ready["Status"] == "created",
            "runtime admission ran after failed provisioning",
        )


class Stack:
    def __init__(self, root, image, label):
        from scripts.registry_config import check as check_configuration

        self.root = root
        root.mkdir(mode=0o700)
        self.name = "librarium-runtime-" + label + "-" + secrets.token_hex(4)
        self.env = dict(os.environ)
        self.env.update(
            LIBRARIUM_PROJECT_NAME=self.name,
            LIBRARIUM_DATA_ROOT=str(root),
            LIBRARIUM_EDGE_NETWORK=self.name + "-edge",
            LIBRARIUM_IMAGE=image,
            LIBRARIUM_PUBLIC_ORIGIN="https://lib.example.org",
            LIBRARIUM_LIBRARY_HOST_PATH=str(root / "library"),
        )
        for name in ("postgres", "catalogue", "artifacts"):
            (root / name).mkdir(mode=0o700 if name == "artifacts" else 0o755)
        subprocess.run(
            [
                "sudo",
                "chown",
                "10001:10001",
                str(root / "artifacts"),
                str(root / "catalogue"),
            ],
            check=True,
        )
        subprocess.run(
            [
                sys.executable,
                str(ROOT / ".github/scripts/native_library_acceptance.py"),
                "prepare",
            ],
            env=self.env,
            check=True,
            capture_output=True,
        )
        self.override = root / "execution.json"
        resolved = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(ROOT / "compose.registry-workspace.yaml"),
                "config",
                "--format",
                "json",
            ],
            env=self.env,
            capture_output=True,
            check=True,
        )
        model = json.loads(resolved.stdout)
        require(
            set(model["services"])
            == {
                "db",
                "initialize",
                "runtime-login",
                "provision",
                "runtime-ready",
                "web",
                "worker",
            },
            "selected workspace entry lacks the deployed admission chain",
        )
        validation = json.loads(resolved.stdout)
        for role in ("initialize", "provision", "runtime-ready", "web", "worker"):
            require(
                model["services"][role]["image"] == image,
                "selected workspace role changed the accepted image",
            )
            # Configuration fixture only; execution below uses the actual accepted image.
            validation["services"][role]["image"] = (
                "ghcr.io/jshauns81/librarium@sha256:" + "a" * 64
            )
            model["services"][role]["pull_policy"] = "never"
        check_configuration(validation)
        model["networks"]["edge"]["internal"] = True
        self.override.write_text(json.dumps(model))
        self.override.chmod(0o600)
        self.entry = self.override
        self.created = False

    def prepare_catalogue(self):
        output = self.compose(
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "--volume",
            f"{self.root / 'catalogue'}:/runtime-catalogue:rw",
            "web",
            "python",
            "-",
            "prepare-catalogue",
            "/runtime-catalogue",
            data=REFERENCE.read_bytes(),
        ).stdout
        self.catalogue_pin = json.loads(output)

    def run(self, args, *, data=None, output=None, check=True, timeout=240):
        result = subprocess.run(
            args,
            check=False,
            input=data,
            stdout=output or subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            timeout=timeout,
        )
        if check and result.returncode:
            # Only synthetic state is used, but error output may contain credentials.
            print(safe_diagnostics(result.stderr, self.env), file=sys.stderr)
            operation = args[1] if args[:1] == ["docker"] else "command"
            raise RuntimeError(
                f"synthetic runtime acceptance {operation} refused (exit {result.returncode})"
            )
        return result

    def compose(self, *args, **kwargs):
        self.created = True
        try:
            return self.run([*fresh_command(self), *args], **kwargs)
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            if args and args[0] == "up":
                for detail in (("ps", "--all"), ("logs", "--no-color", "--tail", "20")):
                    try:
                        diagnostic = self.run(
                            [*fresh_command(self), *detail], check=False, timeout=30
                        )
                        print(
                            safe_diagnostics(
                                diagnostic.stdout + diagnostic.stderr, self.env
                            ),
                            file=sys.stderr,
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        print("Startup diagnostics unavailable", file=sys.stderr)
            raise RuntimeError(f"Compose {args[0]} failed: {error}") from None

    def sql(self, sql, *, database="librarium", check=True):
        return (
            self.compose(
                "exec",
                "-T",
                "db",
                "psql",
                "-X",
                "-qAt",
                "--set=ON_ERROR_STOP=1",
                "-U",
                "librarium",
                "-d",
                database,
                data=sql.encode(),
                check=check,
            )
            .stdout.decode()
            .strip()
        )

    def roles_absent(self):
        require(
            self.sql("SELECT count(*) FROM pg_roles WHERE rolname='librarium_runtime'")
            == "0",
            "fresh cluster unexpectedly has runtime role",
        )

    def check_runtime(self):
        for service in ("web", "worker"):
            output = self.compose(
                "exec", "-T", service, "python", "-c", ROLE_CHECK.read_text()
            ).stdout
            require(
                json.loads(output)
                == {
                    "current_user": "librarium_runtime",
                    "runtime_grants_verified": True,
                },
                "foreground role did not use the deployed runtime credentials",
            )
        # Exercise real denials in addition to the read-only grant census.
        denial = """import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','librarium.settings')
import django; django.setup()
from django.db import connection,transaction,DatabaseError
for statement in ('CREATE TEMP TABLE forbidden(id integer)',
                  'TRUNCATE librarium_deliveryevent CASCADE',
                  'SET session_replication_role = replica'):
 try:
  with transaction.atomic(),connection.cursor() as c:c.execute(statement)
 except DatabaseError as error:
  if getattr(error.__cause__,'sqlstate',None)!='42501':raise
  continue
 raise AssertionError('runtime owner capability admitted')
print('Runtime SQL denials verified')
"""
        self.compose("exec", "-T", "web", "python", "-c", denial)

    def foreground_not_running(self):
        for service in ("web", "worker"):
            ids = self.compose("ps", "-a", "-q", service).stdout.decode().split()
            for identity in ids:
                state = self.run(
                    ["docker", "inspect", "--format", "{{.State.Running}}", identity]
                ).stdout
                require(
                    state.strip() == b"false", "failed gate admitted foreground process"
                )

    def gate_state(self, service):
        ids = self.compose("ps", "-a", "-q", service).stdout.decode().split()
        require(len(ids) <= 1, "ambiguous runtime gate identity")
        if not ids:
            return None
        return json.loads(
            self.run(
                ["docker", "inspect", "--format", "{{json .State}}", ids[0]]
            ).stdout
        )

    def reject_extra_grants(self):
        for privilege in ("MAINTAIN", "UPDATE(id)"):
            self.sql(
                f"GRANT {privilege} ON librarium_deliveryevent TO librarium_runtime"
            )
            try:
                attempt = self.compose(
                    "exec",
                    "-T",
                    "web",
                    "python",
                    "-c",
                    ROLE_CHECK.read_text(),
                    check=False,
                )
                require(attempt.returncode != 0, "unexpected runtime grant admitted")
            finally:
                self.sql(
                    f"REVOKE {privilege} ON librarium_deliveryevent FROM librarium_runtime"
                )

    def close(self):
        if self.created:
            self.compose("down", "--remove-orphans")
            remaining = self.run(
                [
                    "docker",
                    "ps",
                    "-aq",
                    "--filter",
                    "label=com.docker.compose.project=" + self.name,
                ]
            ).stdout.strip()
            require(not remaining, "owned project containers remain after cleanup")


def acceptance(image, output, expected_config=None):
    actual = subprocess.check_output(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True
    ).strip()
    if expected_config:
        require(actual == expected_config, "accepted image config differs")
    output.mkdir(mode=0o700)
    stacks = []
    result = {
        "schema": "librarium.runtime-startup-proof.v1",
        "image": image,
        "image_config": actual,
    }
    try:
        current = Stack(output / "current", image, "current")
        stacks.append(current)
        current.prepare_catalogue()
        current.compose("up", "-d", "--wait", "--wait-timeout", "180", "web", "worker")
        current.check_runtime()
        current.reject_extra_grants()
        current.compose(
            "exec", "-T", "web", "python", "-", "create", data=EPUB.read_bytes()
        )
        current.compose("stop", "web", "worker")
        require(
            current.sql(
                "SELECT count(*) FROM librarium_job WHERE state IN ('queued','running')"
            )
            == "0",
            "work was not drained before capture",
        )
        original_jobs = current.sql(
            "SELECT id::text||':'||request_key::text FROM librarium_job ORDER BY id"
        )
        original_cluster = current.sql(
            "SELECT system_identifier FROM pg_control_system()"
        )
        dump = output / "current.dump"
        with dump.open("xb") as stream:
            current.compose(
                "exec",
                "-T",
                "db",
                "pg_dump",
                "-U",
                "librarium",
                "-d",
                "librarium",
                "-Fc",
                output=stream,
            )
        dump.chmod(0o600)
        archive = output / "artifacts.tar"
        with archive.open("xb") as stream:
            current.compose(
                "run",
                "--rm",
                "-T",
                "--no-deps",
                "web",
                "python",
                "-",
                "backup",
                data=EPUB.read_bytes(),
                output=stream,
            )
        archive.chmod(0o600)
        fresh = Stack(output / "fresh", image, "fresh")
        stacks.append(fresh)
        fresh.prepare_catalogue()
        fresh.compose("up", "-d", "--wait", "--wait-timeout", "120", "db")
        fresh.roles_absent()
        require(
            fresh.sql("SELECT system_identifier FROM pg_control_system()")
            != original_cluster,
            "restore did not use a fresh PostgreSQL cluster",
        )
        fresh.compose(
            "exec", "-T", "db", "createdb", "-U", "librarium", "negative_acl_restore"
        )
        with dump.open("rb") as stream:
            # This intentional old-contract failure must not be mistaken for recovery.
            failed = fresh.run(
                [
                    *fresh_command(fresh),
                    "exec",
                    "-T",
                    "db",
                    "pg_restore",
                    "--exit-on-error",
                    "-U",
                    "librarium",
                    "-d",
                    "negative_acl_restore",
                ],
                data=stream.read(),
                check=False,
            )
        require(
            failed.returncode != 0 and b"librarium_runtime" in failed.stderr,
            "missing-login restore regression was not reproduced",
        )
        fresh.compose(
            "exec",
            "-T",
            "db",
            "pg_restore",
            "--exit-on-error",
            "--no-privileges",
            "-U",
            "librarium",
            "-d",
            "librarium",
            data=dump.read_bytes(),
        )
        fresh.roles_absent()
        extract = "import sys,tarfile;tarfile.open(fileobj=sys.stdin.buffer,mode='r|').extractall('/artifacts',filter='data')"
        fresh.compose(
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "web",
            "python",
            "-c",
            extract,
            data=archive.read_bytes(),
        )
        fresh.compose("up", "-d", "--wait", "--wait-timeout", "180", "web", "worker")
        fresh.check_runtime()
        require(
            fresh.sql(
                "SELECT id::text||':'||request_key::text FROM librarium_job ORDER BY id"
            )
            == original_jobs,
            "restored historical jobs changed",
        )
        fresh.compose(
            "exec", "-T", "web", "python", "-", "verify", data=EPUB.read_bytes()
        )
        result.update(
            fresh_cluster_restore=True,
            runtime_absent_before_restore=True,
            no_privileges_restore=True,
            job_keys_preserved=True,
            source_report_output_bindings=True,
            dump_sha256=hashlib.sha256(dump.read_bytes()).hexdigest(),
            artifacts_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        )
        for failure in ("wrong_password", "elevated_role", "provision_failure"):
            blocked = Stack(output / failure, image, failure.replace("_", "-"))
            stacks.append(blocked)
            blocked.prepare_catalogue()
            if failure == "provision_failure":
                override = json.loads(blocked.override.read_text())
                override["services"]["provision"]["command"] = [
                    "python",
                    "-c",
                    "raise SystemExit(1)",
                ]
                blocked.override.write_text(json.dumps(override))
            blocked.compose("up", "-d", "--wait", "--wait-timeout", "120", "db")
            if failure != "provision_failure":
                attrs = "SUPERUSER" if failure == "elevated_role" else "NOSUPERUSER"
                password = (
                    blocked.env["LIBRARIUM_RUNTIME_DB_PASSWORD"]
                    if failure == "elevated_role"
                    else "intentionally-wrong-synthetic-password"
                )
                # Synthetic secret goes over stdin only, never argv or output.
                blocked.sql(
                    "CREATE ROLE librarium_runtime LOGIN "
                    + attrs
                    + " PASSWORD '"
                    + password.replace("'", "''")
                    + "';"
                )
            attempt = blocked.compose(
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "120",
                "web",
                "worker",
                check=False,
            )
            require(attempt.returncode != 0, "invalid existing login was accepted")
            failure_phases(
                failure,
                blocked.gate_state("provision"),
                blocked.gate_state("runtime-ready"),
            )
            blocked.foreground_not_running()
        result.update(
            wrong_password_blocks_admission=True,
            elevated_role_blocks_admission=True,
            failed_provision_blocks_admission=True,
            unexpected_table_and_column_grants_refused=True,
            catalogue_fixture=current.catalogue_pin,
            outcome="passed",
            configuration_sha256={
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in [
                    "compose.registry.yaml",
                    "compose.runtime.yaml",
                    "compose.registry-workspace.yaml",
                    "scripts/runtime_identity.py",
                    "scripts/runtime_login.sql",
                ]
            },
        )
    finally:
        cleanup = []
        for stack in reversed(stacks):
            try:
                stack.close()
                cleanup.append({"project": stack.name, "stopped": True})
            except Exception:  # noqa: BLE001 - attempt cleanup of every owned project.
                cleanup.append({"project": stack.name, "stopped": False})
        cleanup_path = output / "cleanup.json"
        cleanup_path.write_text(json.dumps(cleanup, indent=2) + "\n")
        cleanup_path.chmod(0o600)
        require(
            all(row["stopped"] for row in cleanup),
            "owned runtime acceptance cleanup incomplete",
        )
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        "PASS: composed runtime startup, failure admission gates and fresh-cluster recovery"
    )
    return result


def fresh_command(stack):
    return [
        "docker",
        "compose",
        "--project-name",
        stack.name,
        "-f",
        str(stack.entry),
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--expected-config")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    acceptance(args.image, args.output, args.expected_config)
