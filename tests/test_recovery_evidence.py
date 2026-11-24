"""Retained rehearsal evidence is bounded reporting, never recovery authority."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from librarium import recovery_evidence as evidence

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)
CANARY = "private-canary.invalid/private-account/secret"


@pytest.fixture
def receipt():
    return {
        "schema": "librarium.recovery-rehearsal.v1",
        "scope": "isolated_epub_database_artifacts",
        "outcome": "passed",
        "backup_captured_at": "2026-11-01T11:00:00Z",
        "recovery_started_at": "2026-11-01T11:01:00Z",
        "recovery_completed_at": "2026-11-01T11:01:10Z",
        "recovery_seconds": 10.0,
        "binding": {
            "source_sha256": "a" * 64,
            "build_identity_sha256": "b" * 64,
            "compatibility_sha256": "c" * 64,
        },
        "assertions": [
            "database_reopened",
            "original_bytes",
            "inspection_report",
            "validation_report",
        ],
    }


def saved(tmp_path, receipt):
    root = tmp_path / "retained"
    root.mkdir(mode=0o700)
    path = root / "rehearsal.json"
    path.write_text(json.dumps(receipt))
    path.chmod(0o600)
    return path


def test_receipt_projection_is_closed_and_missing_identity_is_incomplete(tmp_path, receipt):
    result = evidence.report_recovery(saved(tmp_path, receipt), None, NOW)
    assert result["state"] == "incomplete"
    assert result["recovery_seconds"] == 10.0
    assert result["backup_age_at_recovery_seconds"] == 60
    assert result["backup_age_seconds"] == 3600
    assert result["authority"] == "reporting_only"
    assert result["running_image_verified"] is False


@pytest.mark.parametrize(
    "mutation,state",
    [
        (lambda r: r.update(schema="unsupported"), "unsupported"),
        (lambda r: r.update(extra=CANARY), "invalid"),
        (lambda r: r.update(recovery_seconds=True), "invalid"),
        (lambda r: r.update(recovery_seconds=float("nan")), "invalid"),
        (lambda r: r.update(recovery_seconds=-1), "invalid"),
        (lambda r: r.update(recovery_seconds=86401), "invalid"),
        (lambda r: r.update(outcome="unverified"), "invalid"),
        (lambda r: r.update(backup_captured_at="2026-11-02T11:00:00Z"), "invalid"),
        (
            lambda r: r.update(
                backup_captured_at="2026-11-01T13:00:00Z",
                recovery_started_at="2026-11-01T13:01:00Z",
                recovery_completed_at="2026-11-01T13:01:10Z",
            ),
            "future",
        ),
        (lambda r: r.update(assertions=["database_reopened"]), "invalid"),
        (lambda r: r["binding"].update(source_sha256=CANARY), "invalid"),
    ],
)
def test_rejects_bad_receipts_without_echoing_input(tmp_path, receipt, mutation, state):
    mutation(receipt)
    result = evidence.report_recovery(saved(tmp_path, receipt), None, NOW)
    assert result["state"] == state
    assert CANARY not in json.dumps(result)
    assert result["recovery_seconds"] is None


def test_expired_rehearsal_and_capture_currency_are_distinct(tmp_path, receipt):
    path = saved(tmp_path, receipt)
    stale = evidence.report_recovery(path, None, NOW + timedelta(days=31))
    assert stale["state"] == "stale" and stale["rehearsal_current"] is False
    assert stale["backup_current"] is False
    older = evidence.report_recovery(path, None, NOW + timedelta(days=2))
    assert older["state"] == "incomplete" and older["rehearsal_current"] is True
    assert older["backup_current"] is False


@pytest.mark.parametrize(
    "kind", ["malformed", "duplicate", "oversized", "symlink", "hardlink", "public", "fifo"]
)
def test_unsafe_evidence_is_bounded_and_unavailable(tmp_path, receipt, kind):
    import os

    path = saved(tmp_path, receipt)
    if kind == "malformed":
        path.write_text(CANARY)
    elif kind == "duplicate":
        path.write_text('{"schema": 1, "schema": 2}')
    elif kind == "oversized":
        path.write_text(CANARY * evidence.MAX_RECEIPT_BYTES)
    elif kind == "symlink":
        target = path.with_name("target.json")
        path.rename(target)
        path.symlink_to(target)
    elif kind == "hardlink":
        os.link(path, path.with_name("alias.json"))
    elif kind == "public":
        path.chmod(0o644)
    else:
        path.unlink()
        os.mkfifo(path, 0o600)
    result = evidence.report_recovery(path, None, NOW)
    assert result["state"] in {"invalid", "unavailable"}
    assert CANARY not in json.dumps(result)


def test_missing_and_unconfigured_are_truthful(tmp_path):
    assert evidence.report_recovery(None, None, NOW)["state"] == "missing"
    assert evidence.report_recovery(tmp_path / "absent", None, NOW)["state"] == "unavailable"


def test_binding_mismatch_cannot_be_reported_compatible(tmp_path, receipt, monkeypatch):
    monkeypatch.setattr(
        evidence,
        "identity_binding",
        lambda identity: {**receipt["binding"], "source_sha256": "d" * 64},
    )
    result = evidence.report_recovery(saved(tmp_path, receipt), {"known": True}, NOW)
    assert result["state"] == "incompatible"
    assert result["binding_matches"] is False


def test_current_matching_retained_evidence_is_reporting_only(tmp_path, receipt, monkeypatch):
    monkeypatch.setattr(evidence, "identity_binding", lambda identity: deepcopy(receipt["binding"]))
    result = evidence.report_recovery(saved(tmp_path, receipt), {"known": True}, NOW)
    assert result["state"] == "recorded" and result["binding_matches"] is True
    assert result["provenance"] == "retained_operator_evidence"
    assert result["backup_current"] is True
    assert result["authority"] == "reporting_only"


def test_unbuilt_receipt_never_gains_compatible_binding(tmp_path, receipt, monkeypatch):
    receipt["binding"] = dict.fromkeys(receipt["binding"])
    monkeypatch.setattr(
        evidence,
        "identity_binding",
        lambda identity: {
            "source_sha256": "a" * 64,
            "build_identity_sha256": "b" * 64,
            "compatibility_sha256": "c" * 64,
        },
    )
    assert (
        evidence.report_recovery(saved(tmp_path, receipt), {"known": True}, NOW)["state"]
        == "incomplete"
    )


@pytest.mark.parametrize("seconds", [0.5, 13.0])
def test_duration_must_agree_with_receipt_wall_interval(tmp_path, receipt, seconds):
    receipt["recovery_seconds"] = seconds
    result = evidence.report_recovery(saved(tmp_path, receipt), None, NOW)
    assert result["state"] == "invalid"
    assert result["recovery_seconds"] is None
