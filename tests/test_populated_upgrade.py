"""Safety boundaries of the disposable populated rehearsal, without live targets."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import populated_upgrade as upgrade


@pytest.fixture
def candidate_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    upgrade.git(repo, "init", "-q")
    upgrade.git(repo, "config", "user.name", "Fixture Maintainer")
    upgrade.git(repo, "config", "user.email", "fixture@example.invalid")
    upgrade.git(repo, "config", "commit.gpgsign", "false")
    upgrade.git(repo, "config", "core.hooksPath", str(tmp_path / "empty-hooks"))
    app = repo / "backend/librarium"
    app.mkdir(parents=True)
    (app / "epub_inspection.py").write_text('POLICY_VERSION = "fixture.inspection.v1"\n')
    (app / "epubcheck_process.py").write_text(
        'VALIDATION_POLICY: dict = {"version": "fixture.validation.v1"}\n'
    )
    upgrade.git(repo, "add", "backend")
    upgrade.git(repo, "commit", "-qm", "Candidate fixture")
    return repo


def test_candidate_export_uses_the_selected_commit_after_head_advances(tmp_path, candidate_repo):
    selected = upgrade.git(candidate_repo, "rev-parse", "HEAD").decode().strip()
    tree = upgrade.git(candidate_repo, "rev-parse", "HEAD^{tree}").decode().strip()
    policy_file = Path("backend/librarium/epub_inspection.py")
    original = (candidate_repo / policy_file).read_bytes()
    (candidate_repo / policy_file).write_text('POLICY_VERSION = "fixture.inspection.v2"\n')
    upgrade.git(candidate_repo, "commit", "-qam", "Updated candidate")

    target = tmp_path / "export"
    receipt = upgrade.export_source(candidate_repo, selected, target)
    assert receipt["commit"] == selected
    assert receipt["tree"] == tree
    assert receipt["policy"]["inspection_policy"] == "fixture.inspection.v1"
    assert (target / policy_file).read_bytes() == original


def test_missing_candidate_revision_refused_before_export(tmp_path, candidate_repo):
    target = tmp_path / "export"
    with pytest.raises(subprocess.CalledProcessError):
        upgrade.export_source(candidate_repo, "missing-ref", target)
    assert not target.exists()


def test_candidate_symlink_refused_before_export(tmp_path, candidate_repo):
    (candidate_repo / "link").symlink_to("backend/librarium/epub_inspection.py")
    upgrade.git(candidate_repo, "add", "link")
    upgrade.git(candidate_repo, "commit", "-qm", "Unsafe fixture entry")

    target = tmp_path / "export"
    with pytest.raises(ValueError, match="source_link_or_mode"):
        upgrade.export_source(candidate_repo, "HEAD", target)
    assert not target.exists()


def test_incompatible_roles_and_image_only_rollback_refused():
    state = upgrade.Supervision()
    state.start("old-web", "old")
    with pytest.raises(ValueError, match="overlap"):
        state.start("new-worker", "current")
    with pytest.raises(ValueError, match="stopped"):
        state.migrated()
    state.stop("old-web")
    state.migrated()
    with pytest.raises(ValueError, match="image_only_rollback"):
        state.start("old-web", "old")
    state.start("new-worker", "current")


def test_incomplete_and_altered_capture_refused(tmp_path):
    dump = tmp_path / "db.dump"
    dump.write_bytes(b"synthetic-dump")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(mode=0o700)
    artifact = artifacts / "source-test"
    artifact.write_bytes(b"synthetic-epub")
    artifact.chmod(0o400)
    capture = upgrade.capture_files(dump, artifacts)
    upgrade.verify_capture(capture, dump, artifacts)
    for change in ["content", "mode", "owner", "missing_dump", "missing_artifact"]:
        altered = json.loads(json.dumps(capture))
        if change == "content":
            artifact.chmod(0o600)
            artifact.write_bytes(b"altered")
        elif change == "mode":
            artifact.chmod(0o600)
        elif change == "owner":
            altered["artifacts"]["files"]["source-test"]["uid"] += 1
        elif change == "missing_dump":
            altered.pop("database_sha256")
        else:
            artifact.unlink()
        with pytest.raises((ValueError, OSError)):
            upgrade.verify_capture(altered, dump, artifacts)
        if not artifact.exists():
            artifact.write_bytes(b"synthetic-epub")
        else:
            artifact.chmod(0o600)
            artifact.write_bytes(b"synthetic-epub")
        artifact.chmod(0o400)


def test_failed_migration_cannot_start_current():
    state = upgrade.Supervision()
    with pytest.raises(ValueError, match="not_migrated"):
        state.start("current-worker", "current")


def test_policy_mismatch_refused():
    with pytest.raises(ValueError, match="baseline_policy"):
        upgrade.check_baseline_policy({"inspection_policy": "future"})


def test_symlink_artifact_refused(tmp_path):
    (tmp_path / "artifact").symlink_to("elsewhere")
    with pytest.raises(ValueError, match="artifact"):
        upgrade.inventory(tmp_path)


@pytest.mark.parametrize("scope", ["isolated_populated_upgrade", "isolated_pre_upgrade_generation"])
def test_recovery_owner_retains_precise_upgrade_scopes(tmp_path, scope):
    from datetime import UTC, datetime, timedelta

    from librarium import recovery_evidence as evidence

    now = datetime.now(UTC)
    record = evidence.make_receipt(
        scope,
        now - timedelta(seconds=5),
        now - timedelta(seconds=2),
        now,
        2,
        evidence.identity_binding(None),
    )
    path = tmp_path / "receipt.json"
    tmp_path.chmod(0o700)
    evidence.retain_receipt(path, record)
    projected = evidence.report_recovery(path, None, now)
    assert projected["state"] == "incomplete"
    assert projected["scope"] == scope
    assert projected["backup_age_at_recovery_seconds"] == 3
    assert projected["running_image_verified"] is False
    assert ("retired_history_readable" in record["assertions"]) == (
        scope == "isolated_populated_upgrade"
    )
    assert not {"corrected_copy", "preservation"} & set(record["assertions"])
    assert "no_resend" not in record["assertions"]


def test_image_actor_is_bound_to_disposable_db_and_does_not_inherit_runtime_credentials(tmp_path):
    runner = upgrade.Runner(tmp_path, docker=True)
    runner.images = {"old": "sha256:" + "a" * 64, "current": "sha256:" + "b" * 64}
    runner.runtime_env = {
        "LIBRARIUM_RUNTIME_DB_USER": "upgrade_runtime",
        "LIBRARIUM_RUNTIME_DB_PASSWORD": "synthetic-only",
    }
    runner.env.update(PGHOST="owned-disposable-db", PGPORT="5432")
    args, env, _cwd = runner.app_command(
        "current", "current_restore", tmp_path / "artifacts", ["manage.py", "check"]
    )
    assert env["PGDATABASE"] == "current_restore"
    assert env["PGHOST"] == "owned-disposable-db"
    assert env["LIBRARIUM_RUNTIME_DB_USER"] == "upgrade_runtime"
    assert env["PGPASSWORD"] not in args
    assert "synthetic-only" not in args
    assert args[-4:] == ["sha256:" + "b" * 64, "python", "manage.py", "check"]
    old_args, old_env, _ = runner.app_command(
        "old", "old_restore", tmp_path / "old-artifacts", ["manage.py", "check"]
    )
    assert "LIBRARIUM_RUNTIME_DB_USER" not in old_env
    assert old_args[-4] == "sha256:" + "a" * 64


def test_capture_refuses_running_admission_and_workers():
    state = upgrade.Supervision()
    state.start("worker", "old")
    with pytest.raises(ValueError, match="stopped_roles"):
        state.capture()
    state.stop("worker")
    state.capture()


def test_process_launcher_refuses_image_only_rollback_before_any_command(tmp_path):
    runner = upgrade.Runner(tmp_path)
    runner.supervision.migrated()
    with pytest.raises(ValueError, match="image_only_rollback"):
        runner.app("old", "upgrade", tmp_path / "artifacts", "manage.py", "check")


def test_process_launcher_refuses_current_worker_before_migration(tmp_path):
    runner = upgrade.Runner(tmp_path)
    with pytest.raises(ValueError, match="not_migrated"):
        runner.app(
            "current", "upgrade", tmp_path / "artifacts", "manage.py", "inspection_worker", "--once"
        )


def test_image_inventory_respects_exported_docker_exclusions(tmp_path):
    (tmp_path / ".dockerignore").write_text("backend/tests\n**/__pycache__\n**/*.sqlite*\n")
    source = {
        "files": {
            "backend/manage.py": {"sha256": "a"},
            "backend/tests/test_jobs.py": {"sha256": "b"},
            "backend/librarium/data.sqlite": {"sha256": "c"},
        }
    }
    included, excluded = upgrade.image_inventory(source, tmp_path)
    assert included == {"manage.py": "a"}
    assert excluded == ["backend/librarium/data.sqlite", "backend/tests/test_jobs.py"]


def test_failed_migration_requires_expected_failure_and_applied_prefix():
    with pytest.raises(ValueError, match="migration_failure"):
        upgrade.migration_failure_proof(b"authentication failed", ["0007_example"])
    with pytest.raises(ValueError, match="migration_failure"):
        upgrade.migration_failure_proof(
            b'relation "librarium_correctedepub" already exists', ["0008_example"]
        )
    upgrade.migration_failure_proof(
        b'relation "librarium_correctedepub" already exists', ["0007_example"]
    )


def test_other_database_cannot_launch_current_worker_before_migration(tmp_path):
    runner = upgrade.Runner(tmp_path)
    with pytest.raises(ValueError, match="not_migrated"):
        runner.app(
            "current",
            "failed_migration",
            tmp_path / "artifacts",
            "manage.py",
            "inspection_worker",
            "--once",
        )


def test_loss_boundary_requires_current_jobs_absent_from_old_restore():
    old = {"pending": {"id": "old", "state": "queued"}}
    current = {
        "rows": [{"id": "new", "request_key": "key", "result": {"digest": "x"}}],
        "pending_after": {"id": "old", "state": "failed"},
    }
    pre = {"artifacts": {"files": {"original": {"sha256": "a"}}}}
    post = {"artifacts": {"files": {"original": {"sha256": "a"}, "corrected": {"sha256": "b"}}}}
    with pytest.raises(ValueError, match="post_upgrade_jobs"):
        upgrade.loss_boundary(old, current, pre, post, {"old", "new"})
    loss = upgrade.loss_boundary(old, current, pre, post, {"old"})
    assert loss["jobs"][0]["id"] == "new"
    assert loss["artifacts"] == {"corrected": {"sha256": "b"}}
    assert loss["pending_transition"] == {
        "before": old["pending"],
        "after": current["pending_after"],
    }


def test_cleanup_reports_failure_and_still_stops_another_owned_process(tmp_path):
    import subprocess
    import sys

    class Unstoppable:
        def poll(self):
            return None

        def terminate(self):
            raise PermissionError("synthetic denial")

    owned = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    runner = upgrade.Runner(tmp_path)
    runner.processes = [Unstoppable(), owned]
    result = runner.close()
    assert result["stopped"] is False
    assert [x["stopped"] for x in result["resources"]] == [False, True]
    assert owned.poll() is not None


def test_cleanup_failure_preserves_original_rehearsal_error(tmp_path, monkeypatch):
    from argparse import Namespace

    class FailingCleanup:
        def __init__(self, *args):
            pass

        def close(self):
            return {"stopped": False, "resources": [{"stopped": False}]}

    def original(*args, **kwargs):
        raise ValueError("original_source_failure")

    monkeypatch.setattr(upgrade, "Runner", FailingCleanup)
    monkeypatch.setattr(upgrade, "export_source", original)
    output = tmp_path / "rehearsal"
    with pytest.raises(ValueError, match="original_source_failure"):
        upgrade.rehearse(Namespace(output=output, mode="source", pg_bin=None, candidate="HEAD"))
    assert json.loads((output / "cleanup.json").read_text())["stopped"] is False
    assert not (output / "result.json").exists()


def test_image_workflow_setup_resolves_python_and_scopes_git_trust(tmp_path):
    import os
    import subprocess

    repository = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((repository / ".github/workflows/container.yml").read_text())
    steps = workflow["jobs"]["candidate-container"]["steps"]
    (command,) = (
        step["run"] for step in steps if "scripts/populated_upgrade.py" in step.get("run", "")
    )
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".python-version").write_bytes((repository / ".python-version").read_bytes())
    scripts = checkout / "scripts"
    scripts.mkdir()
    (scripts / "populated_upgrade.py").write_text(
        "import json, os, pathlib, platform, subprocess\n"
        "root = pathlib.Path(os.environ['GITHUB_WORKSPACE'])\n"
        "assert platform.python_version() == (root / '.python-version').read_text().strip()\n"
        "env = dict(os.environ, GIT_TEST_ASSUME_DIFFERENT_OWNER='1')\n"
        "def git(path):\n"
        " return subprocess.run(['git', '-C', str(path), 'rev-parse', '--git-dir'], "
        "env=env, capture_output=True, text=True)\n"
        "accepted = git(root)\n"
        "assert accepted.returncode == 0, accepted.stderr\n"
        "refused = git(os.environ['UNTRUSTED_CHECKOUT'])\n"
        "assert refused.returncode != 0 and 'dubious ownership' in refused.stderr\n"
        "print(json.dumps({'python': platform.python_version(), 'other_checkout_refused': True}))\n"
    )
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    subprocess.run(["git", "-C", str(checkout), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=Fixture Maintainer",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "Synthetic workflow checkout",
        ],
        check=True,
    )
    other = tmp_path / "other-checkout"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    # Avoid elevation while reproducing Git's owner check in the synthetic probe.
    sudo = binaries / "sudo"
    sudo.write_text('#!/bin/sh\nexec "$@"\n')
    sudo.chmod(0o700)
    env = dict(
        os.environ,
        PATH=str(binaries) + os.pathsep + os.environ["PATH"],
        GITHUB_WORKSPACE=str(checkout),
        UNTRUSTED_CHECKOUT=str(other),
        RUNNER_TEMP=str(tmp_path),
        CANDIDATE_IMAGE="sha256:" + "a" * 64,
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        UV_OFFLINE="1",
    )
    result = subprocess.run(
        ["bash", "-eu", "-c", command],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["other_checkout_refused"] is True


def test_image_client_version_uses_real_nonconnecting_postgres_parser(tmp_path, monkeypatch):
    import os
    import shutil
    import subprocess

    configured = os.environ.get("LIBRARIUM_POSTGRES_BIN")
    client = str(Path(configured) / "pg_dump") if configured else shutil.which("pg_dump")
    if not client:
        pytest.skip("A PostgreSQL client is required for the real version-parser regression")
    runner = upgrade.Runner(tmp_path, docker=True)
    commands = []

    def execute_client(args, **kwargs):
        commands.append(args)
        # Replace only Docker transport; execute the real client's received arguments.
        return subprocess.check_output(
            [client, *args[args.index("pg_dump") + 1 :]], stderr=subprocess.PIPE, timeout=5
        )

    monkeypatch.setattr(runner, "run", execute_client)
    assert runner.db("pg_dump", "--version").startswith(b"pg_dump (PostgreSQL)")
    assert commands[0][:3] == ["docker", "exec", "-i"]
    assert runner.password not in commands[0]


def test_workflow_exports_only_portable_proof_across_private_directory(tmp_path):
    import os
    import stat
    import subprocess
    import textwrap

    if os.geteuid() == 0:
        pytest.skip("The shell permission boundary requires an unprivileged test user")
    repository = Path(__file__).resolve().parents[1]
    workflow = (repository / ".github/workflows/container.yml").read_text()
    step = workflow.split("      - name: Copy portable proof for artifact upload\n", 1)[1].split(
        "\n      - ", 1
    )[0]
    command = textwrap.dedent(step.split("        run: |\n", 1)[1])
    private = tmp_path / "populated-upgrade"
    receipts = private / "receipts"
    receipts.mkdir(parents=True, mode=0o700)
    (private / "result.json").write_text('{"outcome":"passed"}')
    names = [
        "fixture.json",
        "current-fixture.json",
        "isolated_populated_upgrade.json",
        "isolated_pre_upgrade_generation.json",
    ]
    for name in names:
        (receipts / name).write_text('{"scope":"synthetic"}')
    (receipts / "private-extra.json").write_text('{"private":"do not export"}')
    (private / "failure.log").write_text("private diagnostic")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    sudo = binaries / "sudo"
    # Grant access only inside the synthetic privileged invocation, then restore it.
    sudo.write_text(
        '#!/bin/sh\nprivate="$RUNNER_TEMP/populated-upgrade"\n'
        'chmod 700 "$private" "$private/receipts"\n'
        'trap \'chmod 000 "$private/receipts" "$private"\' EXIT\n'
        '"$@"\n'
    )
    sudo.chmod(0o700)
    try:
        receipts.chmod(0o000)
        private.chmod(0o000)
        result = subprocess.run(
            ["bash", "-eu", "-c", command],
            env=dict(
                os.environ,
                PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                RUNNER_TEMP=str(tmp_path),
            ),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert stat.S_IMODE(private.stat().st_mode) == 0
    finally:
        private.chmod(0o700)
        receipts.chmod(0o700)
    assert result.returncode == 0, result.stderr
    exported = tmp_path / "populated-proof"
    assert {p.name for p in exported.iterdir()} == {"result.json", *names}
    assert all(
        p.read_bytes()
        == (private / p.name if p.name == "result.json" else receipts / p.name).read_bytes()
        for p in exported.iterdir()
    )


def test_rehearsal_accepts_the_cover_search_schema_leaf():
    upgrade.require_candidate_schema(upgrade.source_policy(Path.cwd()))
    with pytest.raises(ValueError, match="candidate_schema_mismatch"):
        upgrade.require_candidate_schema({"migration_leaves": ["0014_prepared_cover"]})


def test_rehearsal_checks_cover_search_runtime_grants(tmp_path, monkeypatch):
    runner = upgrade.Runner(tmp_path)
    calls = []

    def db(*args):
        calls.append(args)
        return b"t\n"

    monkeypatch.setattr(runner, "db", db)
    runner.verify_cover_runtime("upgrade")
    query = calls[0][-1]
    assert all(table in query for table in ("librarium_coversearch", "librarium_sourcebrowserpage"))
    assert "upgrade_runtime" in query
    assert all(
        privilege in query
        for privilege in (
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "TRUNCATE",
            "REFERENCES",
            "TRIGGER",
        )
    )
    monkeypatch.setattr(runner, "db", lambda *args: b"f\n")
    with pytest.raises(ValueError, match="cover_search_runtime_grants_mismatch"):
        runner.verify_cover_runtime("upgrade")


def test_rehearsal_refuses_missing_cover_search_table_columns(tmp_path, monkeypatch):
    runner = upgrade.Runner(tmp_path)
    replies = iter([b"0015_cover_search\n", b"id\n"])
    monkeypatch.setattr(runner, "db", lambda *args: next(replies))
    with pytest.raises(ValueError, match="cover_search_schema_mismatch"):
        runner.verify_schema(
            "upgrade",
            {
                "files": ["backend/librarium/migrations/0015_cover_search.py"],
                "policy": {"migration_leaves": ["0015_cover_search"]},
            },
        )


@pytest.mark.parametrize("damage", [None, "source_timings", "browser_table"])
def test_current_leaf_checks_timings_and_browser_cache_columns(tmp_path, monkeypatch, damage):
    runner = upgrade.Runner(tmp_path)
    leaf = "0017_cover_source_timings"
    columns = {
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
        "source_timings",
    }
    if damage == "source_timings":
        columns.remove("source_timings")
    browser = [] if damage == "browser_table" else ["query_key", "html", "url", "checked_at"]
    replies = iter([leaf.encode(), "\n".join(columns).encode(), "\n".join(browser).encode()])
    monkeypatch.setattr(runner, "db", lambda *args: next(replies))
    source = {
        "files": [f"backend/librarium/migrations/{leaf}.py"],
        "policy": {"migration_leaves": [leaf]},
    }
    if damage:
        with pytest.raises(
            ValueError,
            match="cover_search_schema_mismatch"
            if damage == "source_timings"
            else "browser_cache_schema_mismatch",
        ):
            runner.verify_schema("upgrade", source)
    else:
        runner.verify_schema("upgrade", source)
        with pytest.raises(StopIteration):
            next(replies)
