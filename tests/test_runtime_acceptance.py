"""Public diagnostics must retain failures without disclosing synthetic credentials."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".github/scripts/runtime_container_acceptance.py"
)
SPEC = importlib.util.spec_from_file_location("runtime_acceptance", SCRIPT)
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


def test_startup_diagnostics_redact_credentials_and_keep_service_failure():
    owner = "owner-" + "x" * 48
    runtime = "runtime-" + "y" * 48
    output = f"runtime-login exited 1\nPGPASSWORD={owner}\nRUNTIME_PASSWORD={runtime}"
    safe = acceptance.safe_diagnostics(
        output.encode(),
        {"LIBRARIUM_DB_PASSWORD": owner, "LIBRARIUM_RUNTIME_DB_PASSWORD": runtime},
    )
    assert "runtime-login exited 1" in safe
    assert owner not in safe
    assert runtime not in safe
    assert safe.count("[REDACTED]") == 2


def test_diagnostics_redact_before_bounding_output():
    secret = "synthetic-" + "z" * 48
    safe = acceptance.safe_diagnostics(
        ("prefix\n" * 4000 + secret + "\nprovision failed").encode(),
        {"LIBRARIUM_SECRET_KEY": secret},
    )
    assert len(safe) <= 16384
    assert safe.endswith("[REDACTED]\nprovision failed")
    assert secret not in safe


def test_command_failure_prints_only_redacted_detail(monkeypatch, capsys):
    secret = "synthetic-" + "s" * 48
    stack = acceptance.Stack.__new__(acceptance.Stack)
    stack.env = {"LIBRARIUM_RUNTIME_DB_PASSWORD": secret}
    monkeypatch.setattr(
        acceptance.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, b"", f"runtime-login exited 1: {secret}".encode()
        ),
    )
    with pytest.raises(RuntimeError, match="compose refused \\(exit 1\\)"):
        stack.run(["docker", "compose"])
    output = capsys.readouterr().err
    assert "runtime-login exited 1" in output
    assert secret not in output


def test_elevated_role_case_cannot_pass_for_a_wrong_password():
    success = {"Status": "exited", "ExitCode": 0}
    refused = {"Status": "exited", "ExitCode": 1}
    with pytest.raises(RuntimeError, match="provisioning"):
        acceptance.failure_phases("elevated_role", success, refused)
    acceptance.failure_phases("wrong_password", success, refused)


def test_password_case_cannot_pass_for_failed_provisioning():
    refused = {"Status": "exited", "ExitCode": 1}
    with pytest.raises(RuntimeError, match="reach runtime"):
        acceptance.failure_phases("wrong_password", refused, None)
    acceptance.failure_phases("elevated_role", refused, {"Status": "created"})
