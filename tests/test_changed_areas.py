import importlib.util
from pathlib import Path

import pytest

from scripts.dev import verify_status_docs

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "changed_areas", ROOT / ".github/scripts/changed_areas.py"
)
changed_areas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(changed_areas)


def test_docs_only_change_skips_code_checks():
    for paths in (["AGENTS.md", "docs/decisions.md"], ["docs/status/2026-11-06-example.md"]):
        assert changed_areas.areas(paths) == {
            "python": False,
            "frontend": False,
            "docs": True,
            "candidate_container": False,
            "populated_upgrade": False,
        }


def test_status_docs_layout_remains_valid():
    assert verify_status_docs(ROOT) >= 36


def test_code_frontend_and_workflow_changes_select_their_checks():
    assert changed_areas.areas(["backend/librarium/views.py"]) == {
        "python": True,
        "frontend": False,
        "docs": False,
        "candidate_container": False,
        "populated_upgrade": False,
    }
    assert changed_areas.areas(["frontend/src/App.tsx"]) == {
        "python": False,
        "frontend": True,
        "docs": False,
        "candidate_container": False,
        "populated_upgrade": False,
    }
    assert changed_areas.areas([".github/workflows/quality.yml"]) == {
        "python": True,
        "frontend": True,
        "docs": False,
        "candidate_container": False,
        "populated_upgrade": False,
    }


def test_no_base_runs_everything(capsys):
    changed_areas.main("")
    assert capsys.readouterr().out.split() == ["python=true", "frontend=true", "docs=true", "candidate_container=true", "populated_upgrade=true"]



def tiers_module():
    import sys

    folder = Path(__file__).resolve().parents[1] / ".github/scripts"
    spec = importlib.util.spec_from_file_location("container_tiers", folder / "container_tiers.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(folder))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def test_container_check_reports_on_every_pull_request():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/container.yml").read_text()
    assert "paths-ignore" not in workflow.split("jobs:", 1)[0]


@pytest.mark.parametrize("selected,current,upgrade", [
    ((False, False), "skipped", "skipped"),
    ((True, False), "success", "success"),
    ((True, True), "success", "success"),
])
def test_container_gate_accepts_only_legitimate_success_or_deferral(selected, current, upgrade):
    tiers = tiers_module()
    found = dict(zip(("candidate_container", "populated_upgrade"), selected))
    passed, rows = tiers.evaluate(found, "success", str(selected[0]).lower(), current, upgrade)
    assert passed
    assert rows[-1][1] == ("succeeded" if selected[1] else "deferred")


@pytest.mark.parametrize("selected,current,upgrade", [
    ((True, True), "success", "failure"),
    ((True, True), "success", "skipped"),
    ((True, True), "success", ""),
    ((True, True), "cancelled", "skipped"),
    ((True, True), "", "success"),
    ((True, False), "success", "failure"),
    ((True, False), "success", "skipped"),
    ((False, False), "failure", "skipped"),
    ((False, False), "success", "success"),
    ((False, False), "skipped", "cancelled"),
])
def test_container_gate_never_hides_failed_or_missing_jobs(selected, current, upgrade):
    found = dict(zip(("candidate_container", "populated_upgrade"), selected))
    passed, rows = tiers_module().evaluate(found, "success", str(selected[0]).lower(), current, upgrade)
    assert not passed
    assert any(state in {"failed", "missing", "unexpected"} for _, state in rows)


@pytest.mark.parametrize("found,changes,code", [
    ({}, "success", "false"),
    ({"candidate_container": "false", "populated_upgrade": False}, "success", "false"),
    ({"candidate_container": False, "populated_upgrade": True}, "success", "false"),
    ({"candidate_container": False, "populated_upgrade": False}, "failure", "false"),
    ({"candidate_container": False, "populated_upgrade": False}, "skipped", "false"),
    ({"candidate_container": False, "populated_upgrade": False}, "success", ""),
    ({"candidate_container": True, "populated_upgrade": False}, "success", "false"),
])
def test_container_gate_fails_on_classification_error_or_disagreement(found, changes, code):
    passed, rows = tiers_module().evaluate(found, changes, code, "skipped", "skipped")
    assert not passed
    assert rows[0] == ("classification", "failed")


@pytest.mark.parametrize("path", [
    "Dockerfile", "Dockerfile.writer", ".dockerignore", ".python-version",
    "pyproject.toml", "uv.lock", "requirements.txt", "compose.runtime.yaml",
    "compose.example.yml", "scripts/build_libarchive.py", "scripts/install_epubcheck.py",
    "scripts/release.py", "scripts/run_delivery_writer.py", "scripts/calibre_delivery_runtime.json",
    "scripts/runtime_identity.py", "scripts/runtime_login.sql", "scripts/registry_config.py",
    "backend/librarium/settings.py", "backend/librarium/epubcheck_distribution.json",
    ".github/scripts/runtime_container_acceptance.py", ".github/scripts/native_library_acceptance.py",
])
def test_packaging_and_runtime_contracts_select_candidate_only(path):
    found = changed_areas.areas([path])
    assert found["candidate_container"] is True
    assert found["populated_upgrade"] is False


@pytest.mark.parametrize("path", [
    "backend/librarium/migrations/0012_example.py", "backend/librarium/build_identity.py",
    "backend/librarium/recovery_evidence.py", "backend/librarium/delivery_recovery.py",
    "backend/librarium/epub_inspection.py", "backend/librarium/epubcheck_process.py",
    "backend/librarium/management/commands/provision_runtime_role.py",
    "scripts/populated_upgrade.py", "scripts/upgrade_fixture.py", "scripts/capture_source.py",
    "tests/test_populated_upgrade.py", "tests/test_upgrade_fixture.py",
    "tests/test_public_upgrade_baseline.py", "tests/fixtures/upgrade-baseline/manifest.json",
    "tests/fixtures/upgrade-baseline/source/backend/example.py.fixture",
    ".github/scripts/epub_container_acceptance.py", ".github/workflows/container.yml",
    ".github/scripts/changed_areas.py", ".github/scripts/container_tiers.py",
])
def test_upgrade_contracts_select_rehearsal_and_its_candidate_image(path):
    found = changed_areas.areas([path])
    assert found["populated_upgrade"] is True
    assert found["candidate_container"] is True


@pytest.mark.parametrize("paths", [
    [], ["docs/ci.md"], ["frontend/src/App.tsx"], ["backend/librarium/views.py"],
    ["tests/test_ci_policy.py"], [".github/workflows/quality.yml"],
    ["backend/librarium/views.py", "frontend/src/App.tsx", "docs/status.md"],
])
def test_ordinary_changes_defer_both_acceptance_tiers(paths):
    found = changed_areas.areas(paths)
    assert found["candidate_container"] is False
    assert found["populated_upgrade"] is False


def test_classification_preserves_path_boundaries_and_sees_removed_rename_sources(monkeypatch):
    from types import SimpleNamespace

    commands = []

    def diff(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(stdout="docs/a file.md\0backend/librarium/migrations/0012_old.py\0")

    monkeypatch.setattr(changed_areas.subprocess, "run", diff)
    found = changed_areas.classify("base")
    assert found["docs"] and found["populated_upgrade"]
    assert "-z" in commands[0] and "--no-renames" in commands[0]


def test_classification_errors_fail_the_cli_and_write_summary(monkeypatch, tmp_path):
    import subprocess

    tiers = tiers_module()

    def broken(base):
        raise subprocess.CalledProcessError(1, "git")

    monkeypatch.setattr(tiers, "classify", broken)
    summary = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert tiers.main("classify", "base") == 1
    assert tiers.main("require", "base") == 1
    assert "| classification | failed |" in summary.read_text()


def test_classifier_routes_locked_output_and_full_release_acceptance(capsys):
    tiers = tiers_module()
    assert tiers.main("classify", "") == 0
    assert capsys.readouterr().out.splitlines() == [
        "candidate_container=true", "populated_upgrade=true", "code=true",
    ]


def test_gate_cli_reports_deferral_and_missing_selection(monkeypatch, tmp_path):
    tiers = tiers_module()
    monkeypatch.setattr(tiers, "classify", lambda base: {
        "candidate_container": True, "populated_upgrade": False,
    })
    summary = tmp_path / "summary"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    for name, value in {
        "CHANGES_RESULT": "success", "CODE_CHANGED": "true",
        "CURRENT_IMAGE_RESULT": "success", "POPULATED_UPGRADE_RESULT": "success",
    }.items():
        monkeypatch.setenv(name, value)
    assert tiers.main("require", "base") == 0
    assert "| populated-upgrade | deferred |" in summary.read_text()
    monkeypatch.setenv("CURRENT_IMAGE_RESULT", "skipped")
    assert tiers.main("require", "base") == 1
    assert "| candidate-container | missing |" in summary.read_text()


def test_workflow_tiers_preserve_beta_export_and_gate_every_expensive_upgrade_step():
    import yaml

    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/container.yml").read_text())
    jobs = workflow["jobs"]
    assert jobs["candidate-container"]["if"] == "needs.changes.outputs.code == 'true'"
    upgrade = jobs["populated-upgrade"]["steps"]
    for step in upgrade:
        if step.get("name") in {"Select populated-upgrade tier", "Report deferred populated upgrade"}:
            continue
        if str(step.get("uses", "")).startswith("actions/checkout@"):
            continue
        assert "steps.areas.outputs.populated_upgrade == 'true'" in step["if"]
    gate = jobs["container"]
    assert gate["if"] == "always()"
    assert gate["needs"] == ["changes", "candidate-container", "populated-upgrade"]
    assert "container_tiers.py require" in gate["steps"][-1]["run"]
    beta = yaml.safe_load((root / ".github/workflows/beta.yml").read_text())
    assert beta["jobs"]["acceptance"]["with"]["export-image"] is True
    assert "inputs.export-image && 'tested-image'" in str(jobs["candidate-container"])


def test_main_push_cannot_cancel_exact_source_beta_acceptance():
    import yaml

    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/container.yml").read_text())
    expression = workflow["concurrency"]["group"]

    def group(name, event, source):
        return (
            expression.replace("${{ github.workflow }}", name)
            .replace("${{ github.event_name }}", event)
            .replace("${{ github.ref }}", "refs/heads/main")
            .replace("${{ inputs.source-sha }}", source)
        )

    beta = group("Publish beta", "workflow_dispatch", "a" * 40)
    assert group("Container acceptance", "push", "") != beta
    assert group("Container acceptance", "workflow_dispatch", "") != beta
    assert group("Publish beta", "workflow_dispatch", "b" * 40) != beta


@pytest.mark.parametrize(
    "path",
    [
        "services/source-browser/browser.cjs",
        "services/source-browser/Dockerfile",
        "services/source-browser/seccomp.json",
        "backend/librarium/source_browser.py",
        "backend/librarium/cover_source_protocol.py",
        "backend/librarium/cover_source_fetch.py",
    ],
)
def test_browser_runtime_changes_select_container_acceptance(path):
    assert changed_areas.areas([path])["candidate_container"] is True
