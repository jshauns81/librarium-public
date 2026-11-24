"""Pinned checker output, resource bounds and offline execution use synthetic inputs."""

import hashlib
import json
import os
import subprocess
import sys
import time
from copy import deepcopy
from pathlib import Path

import pytest
from librarium.epubcheck_process import (
    VALIDATION_POLICY,
    VALIDATOR_IDENTITY,
    ValidationProcessError,
    _collect,
    _normalize,
    _read_json,
    validate_isolated,
)


def raw_report(*, errors=0, warnings=0, messages=None):
    return {
        "checker": {
            "checkerVersion": "5.4.0",
            "path": "candidate.epub",
            "nFatal": 0,
            "nError": errors,
            "nWarning": warnings,
            "nInfo": 0,
            "nUsage": 0,
        },
        "publication": {"title": "PRIVATE_PUBLICATION_SENTINEL"},
        "items": [{"content": "PRIVATE_BODY_SENTINEL"}],
        "messages": messages or [],
    }


def message(*, severity="ERROR", locations=1):
    return {
        "ID": "RSC-005",
        "severity": severity,
        "message": "An original synthetic diagnostic.",
        "locations": [
            {
                "path": "EPUB/chapter.xhtml",
                "line": n + 1,
                "column": -1,
                "context": "PRIVATE_CONTEXT_SENTINEL",
            }
            for n in range(locations)
        ],
    }


def normalized(raw, code=0):
    return _normalize(
        raw, code, b"synthetic", Path("/private/task"), VALIDATION_POLICY, VALIDATOR_IDENTITY
    )


def test_valid_and_warning_only_results_are_conformance_passes_without_readiness():
    for raw in [raw_report(), raw_report(warnings=1, messages=[message(severity="WARNING")])]:
        report = normalized(raw)
        assert report["outcome"] == "passed"
        assert report["ready"] is False
        assert report["content_acceptance"] == "not_checked"
        assert report["policy"] == VALIDATION_POLICY
        assert report["validator"] == VALIDATOR_IDENTITY
        assert report["source_sha256"] == hashlib.sha256(b"synthetic").hexdigest()
        assert report["source_size"] == len(b"synthetic")
        assert "PRIVATE_" not in json.dumps(report)


def test_failed_conformance_preserves_diagnostic_and_source_location():
    report = normalized(raw_report(errors=1, messages=[message()]), 1)
    assert report["outcome"] == "failed"
    assert report["counts"]["error"] == 1
    assert report["messages"][0] == {
        "id": "RSC-005",
        "severity": "ERROR",
        "message": "An original synthetic diagnostic.",
        "locations": [{"path": "EPUB/chapter.xhtml", "line": 1, "column": None}],
    }


def test_aggregate_counts_survive_checker_repetition_limits():
    report = normalized(raw_report(errors=40, messages=[message(locations=25)]), 1)
    assert report["counts"]["error"] == 40
    assert report["message_repetition_limit"] == 25
    assert report["messages_truncated"] is True
    assert len(report["messages"][0]["locations"]) == 25


def test_related_locations_do_not_inflate_the_number_of_checker_messages():
    report = normalized(raw_report(errors=1, messages=[message(locations=3)]), 1)
    assert report["outcome"] == "failed"
    assert report["counts"]["error"] == 1
    assert len(report["messages"][0]["locations"]) == 3
    assert report["messages_truncated"] is False


def test_an_unreported_information_aggregate_stays_unknown():
    raw = raw_report()
    raw["checker"].pop("nInfo")
    assert normalized(raw)["counts"]["info"] is None


def test_publication_locations_normalize_without_accepting_traversal():
    raw = raw_report(errors=1, messages=[message()])
    raw["messages"][0]["locations"][0]["path"] = "././candidate.epub"
    report = normalized(raw, 1)
    assert report["messages"][0]["locations"][0]["path"] == ""
    raw["messages"][0]["locations"][0]["path"] = "EPUB/../candidate.epub"
    with pytest.raises(ValidationProcessError):
        normalized(raw, 1)


@pytest.mark.parametrize("value", [-1.0, True, "1", 0])
def test_location_coordinates_require_actual_positive_integers_or_unknown(value):
    raw = raw_report(errors=1, messages=[message()])
    raw["messages"][0]["locations"][0]["line"] = value
    with pytest.raises(ValidationProcessError):
        normalized(raw, 1)


def test_report_files_refuse_symlinks_oversize_and_duplicate_json_keys(tmp_path):
    original = tmp_path / "original"
    original.write_text('{"checker":{},"checker":{}}')
    with pytest.raises(ValidationProcessError):
        _read_json(original, 1024)
    with pytest.raises(ValidationProcessError):
        _read_json(original, 4)
    link = tmp_path / "report"
    link.symlink_to(original)
    with pytest.raises(OSError):
        _read_json(link, 1024)


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "path",
        "negative",
        "boolean",
        "missing_counts",
        "unknown_severity",
        "no_error_count",
        "wrong_exit",
        "message_type",
    ],
)
def test_unusable_checker_evidence_cannot_be_published_as_a_valid_check(change):
    raw = raw_report(errors=1, messages=[message()])
    code = 1
    if change == "version":
        raw["checker"]["checkerVersion"] = "5.3.0"
    elif change == "path":
        raw["checker"]["path"] = "../another.epub"
    elif change == "negative":
        raw["checker"]["nWarning"] = -1
    elif change == "boolean":
        raw["checker"]["nError"] = True
    elif change == "missing_counts":
        raw["checker"].pop("nFatal")
    elif change == "unknown_severity":
        raw["messages"][0]["severity"] = "SUCCESS"
    elif change == "no_error_count":
        raw["checker"]["nError"] = 0
    elif change == "wrong_exit":
        code = 0
    else:
        raw["messages"] = {"not": "an array"}
    with pytest.raises(ValidationProcessError):
        normalized(raw, code)


def test_nonzero_runtime_exit_without_checker_errors_is_not_a_conformance_failure():
    with pytest.raises(ValidationProcessError):
        normalized(raw_report(), 1)


@pytest.mark.parametrize("field", ["message", "path"])
def test_oversize_diagnostic_fields_are_refused_instead_of_fabricated(field):
    raw = raw_report(errors=1, messages=[message()])
    if field == "path":
        raw["messages"][0]["locations"][0]["path"] = "x" * 8193
    else:
        raw["messages"][0][field] = "x" * 8193
    with pytest.raises(ValidationProcessError):
        normalized(raw, 1)


def test_wrong_source_or_profile_is_rejected_before_a_checker_starts(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("No child should start"))
    with pytest.raises(ValidationProcessError):
        validate_isolated(b"synthetic", "0" * 64, VALIDATION_POLICY, VALIDATOR_IDENTITY)
    altered = deepcopy(VALIDATION_POLICY)
    altered["offline"] = False
    with pytest.raises(ValidationProcessError):
        validate_isolated(
            b"synthetic", hashlib.sha256(b"synthetic").hexdigest(), altered, VALIDATOR_IDENTITY
        )


def process(code):
    return subprocess.Popen(
        [sys.executable, "-I", "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def test_log_and_timeout_bounds_terminate_transport_without_waiting_for_eof():
    child = process("import os,time;os.write(1,b'x'*70000);time.sleep(10)")
    started = time.monotonic()
    try:
        with pytest.raises(ValidationProcessError):
            _collect(child, time.monotonic() + 2, lambda: False)
        assert time.monotonic() - started < 2
    finally:
        os.killpg(child.pid, 9)
        child.wait()
        child.stdout.close()
        child.stderr.close()
    child = process("import time;time.sleep(10)")
    try:
        with pytest.raises(ValidationProcessError) as error:
            _collect(child, time.monotonic() + 0.1, lambda: False)
        assert error.value.code == "timeout"
    finally:
        os.killpg(child.pid, 9)
        child.wait()
        child.stdout.close()
        child.stderr.close()


def test_cancellation_interrupts_checker_transport_promptly():
    child = process("import time;time.sleep(10)")
    try:
        with pytest.raises(ValidationProcessError) as error:
            _collect(child, time.monotonic() + 10, lambda: True)
        assert error.value.code == "interrupted"
    finally:
        os.killpg(child.pid, 9)
        child.wait()
        child.stdout.close()
        child.stderr.close()


def test_native_seccomp_filter_blocks_network_in_a_fresh_process():
    script = """import sys,socket,errno
sys.path.insert(0,'backend')
from librarium.epubcheck_process import deny_network
deny_network()
try: socket.socket()
except PermissionError as error: assert error.errno==errno.EPERM
else: raise AssertionError('Network access remained available')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script], capture_output=True, timeout=5, check=False
    )
    assert result.returncode == 0, result.stderr.decode()


def test_remaining_checker_descendants_stop_before_scratch_cleanup(monkeypatch, tmp_path):
    import librarium.epubcheck_process as checker

    marker = tmp_path / "marker"
    group = tmp_path / "group"
    helper = tmp_path / "checker.py"
    raw = json.dumps(raw_report())
    writer = (
        "import pathlib,time; p=pathlib.Path(" + repr(str(marker)) + ");"
        "\nwhile True: p.write_text(str(time.time_ns()));time.sleep(.01)"
    )
    helper.write_text(
        "import json,os,subprocess,sys,time\n"
        "from pathlib import Path\n"
        "json.load(sys.stdin)\n"
        + f"Path({str(group)!r}).write_text(str(os.getpid()))\n"
        + f"subprocess.Popen([sys.executable,'-I','-c',{writer!r}],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
        + f"while not Path({str(marker)!r}).exists():time.sleep(.01)\n"
        + f"Path('report.json').write_text({raw!r})\n"
    )
    monkeypatch.setattr(checker, "_CHILD_PATH", helper)
    monkeypatch.setattr(checker, "_configuration", lambda: (tmp_path, "/unused/java"))
    monkeypatch.setattr(checker, "_verify_distribution", lambda root: None)
    data = b"synthetic"
    try:
        report = checker.validate_isolated(
            data, hashlib.sha256(data).hexdigest(), VALIDATION_POLICY, VALIDATOR_IDENTITY
        )
        assert report["outcome"] == "passed"
        before = marker.read_bytes()
        time.sleep(0.1)
        assert marker.read_bytes() == before
    finally:
        if group.exists() and (group_pid := group.read_text()):
            try:
                os.killpg(int(group_pid), 9)
            except ProcessLookupError:
                pass


def test_checker_stops_if_its_launcher_exits(tmp_path):
    marker = tmp_path / "marker"
    guard_script = (
        "import sys,pathlib,time;sys.path.insert(0,'backend');"
        "from librarium.epubcheck_process import _parent_guard;"
        "_parent_guard(int(sys.argv[1]));p=pathlib.Path(sys.argv[2]);"
        "\nwhile True:p.write_text(str(time.time_ns()));time.sleep(.01)"
    )
    launcher = (
        "import os,subprocess,sys,time;"
        + f"p=subprocess.Popen([sys.executable,'-I','-c',{guard_script!r},str(os.getpid()),{str(marker)!r}],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True);"
        "print(p.pid,flush=True);time.sleep(10)"
    )
    parent = subprocess.Popen([sys.executable, "-I", "-c", launcher], stdout=subprocess.PIPE)
    assert parent.stdout is not None
    child_id = int(parent.stdout.readline())
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        parent.kill()
        parent.wait()
        time.sleep(0.1)
        before = marker.read_bytes()
        time.sleep(0.1)
        assert marker.read_bytes() == before
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait()
        parent.stdout.close()
        try:
            os.killpg(child_id, 9)
        except ProcessLookupError:
            pass
