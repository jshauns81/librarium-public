"""Parent-owned runtime checks cannot be forged through a child exit status."""

import ctypes
import logging
from unittest.mock import Mock

import pytest
from librarium import inspection_process, python_sandbox
from librarium.epub_inspection import InspectionPolicy


@pytest.mark.parametrize("code", ["sandbox_landlock_unavailable", "sandbox_seccomp_unavailable"])
def test_parent_preflight_refuses_before_launch(monkeypatch, code):
    def refuse():
        raise python_sandbox.SandboxError(code)

    monkeypatch.setattr(python_sandbox, "preflight", refuse, raising=False)
    monkeypatch.setattr(
        inspection_process.subprocess, "Popen", lambda *a, **k: pytest.fail("launched")
    )
    with pytest.raises(inspection_process.InspectionProcessError) as error:
        inspection_process.inspect_isolated(b"x", "a" * 64, InspectionPolicy())
    assert error.value.code == code


@pytest.mark.parametrize("status", [20, 21, 22])
def test_child_cannot_forge_platform_unavailability(tmp_path, monkeypatch, status):
    child = tmp_path / "forged.py"
    child.write_text(f"import sys;sys.exit({status})")
    monkeypatch.setattr(inspection_process, "_CHILD_PATH", child)
    with pytest.raises(inspection_process.InspectionProcessError) as error:
        inspection_process.inspect_isolated(b"synthetic", "a" * 64, InspectionPolicy())
    assert error.value.code == "sandbox_setup_failed"


def test_parent_runtime_evidence_records_observed_and_effective_abi(monkeypatch, caplog):
    library = Mock()
    library.syscall.return_value = 13
    monkeypatch.setattr(python_sandbox, "_library", lambda: library)
    monkeypatch.setattr(python_sandbox, "check_seccomp", lambda: None, raising=False)
    with caplog.at_level(logging.INFO):
        evidence = python_sandbox.preflight()
    assert evidence == {"landlock_abi": 13, "policy_abi": 12}
    assert "Landlock ABI 13; policy ABI 12" in caplog.text
    assert library.syscall.call_count == 1  # No restriction installed in parent.
    assert not library.prctl.called


def test_parent_seccomp_kernel_probe_is_read_only(monkeypatch):
    from librarium import seccomp_sandbox

    library = Mock()
    library.seccomp_init.return_value = 91
    library.seccomp_syscall_resolve_name.return_value = 42
    library.seccomp_rule_add.return_value = 0
    library.seccomp_load.return_value = 0
    monkeypatch.setattr(seccomp_sandbox.ctypes.util, "find_library", lambda name: "libseccomp.so.2")
    monkeypatch.setattr(seccomp_sandbox.ctypes, "CDLL", lambda *a, **k: library)
    library.syscall.return_value = 0
    seccomp_sandbox.check_available()
    assert not library.seccomp_load.called
    assert not library.prctl.called
    assert library.syscall.call_args.args[0:2] == (317, 2)
    assert (
        ctypes.cast(
            library.syscall.call_args.args[3], ctypes.POINTER(ctypes.c_uint32)
        ).contents.value
        == 0x00050000
    )


def test_invalid_input_refuses_without_native_preflight(monkeypatch):
    monkeypatch.setattr(
        python_sandbox, "preflight", lambda: pytest.fail("invalid input probed native dependencies")
    )
    with pytest.raises(inspection_process.InspectionProcessError) as error:
        inspection_process.inspect_isolated(bytearray(b"synthetic"), "a" * 64, InspectionPolicy())
    assert error.value.code is None
