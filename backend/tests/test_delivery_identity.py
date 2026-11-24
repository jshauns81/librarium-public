"""Fresh identity evidence is independent of duplicate census availability."""

import pytest
import test_reference_assessment as fixtures
import trust_store
from librarium import book_assessment

selected = fixtures.selected
library = fixtures.library
catalogue_fixture = fixtures.catalogue_fixture
artifact_store = fixtures.artifact_store
curated = fixtures.curated
untrusted = fixtures.untrusted
pytestmark = pytest.mark.django_db(transaction=True)


def test_current_exact_reference_recheck_does_not_require_a_duplicate_scan(
    selected, curated, monkeypatch, settings
):
    monkeypatch.setattr(
        book_assessment, "_duplicates", lambda *a, **k: pytest.fail("duplicate scan")
    )
    settings.DIRECT_LIBRARY_ROOT = ""
    result = book_assessment.recheck_delivery_identity(
        selected.job,
        selected.pin["version"],
        selected.pin["sha256"],
        "w_fixture",
        reference=curated.pin,
    )
    assert result["reference_authentication"]["status"] == "authenticated_reference_match"
    assert result["source_sha256"] == selected.job.target_id
    assert result["duplicates"] == "not_rechecked"
    assert "content_identity_unconfirmed" not in result["blockers"]


def test_recheck_does_not_reuse_a_revoked_reference_clearance(selected, untrusted, tmp_path):
    def revoke(value):
        value["revocations"] = [
            {
                "reference_id": trust_store.REFERENCE,
                "revoked_at": "2026-02-01T00:00:00Z",
                "reason_code": "curation_withdrawn",
            }
        ]

    store = trust_store.build(
        tmp_path / "revoked", untrusted, selected.raw, selected.pin, edit_registry=revoke
    )
    result = book_assessment.recheck_delivery_identity(
        selected.job,
        selected.pin["version"],
        selected.pin["sha256"],
        "w_fixture",
        reference=store.pin,
    )
    assert "content_identity_unconfirmed" in result["blockers"]
    assert "reference_revoked" in result["reference_authentication"]["reason_codes"]


def test_superseded_catalogue_pin_cannot_authenticate_new_delivery(monkeypatch, settings):
    from contextlib import contextmanager

    from librarium import catalogue

    @contextmanager
    def current(*args, **kwargs):
        yield None, {"version": "new", "sha256": "f" * 64}

    monkeypatch.setattr(catalogue, "snapshot", current)
    with pytest.raises(book_assessment.AssessmentError, match="superseded"):
        book_assessment.recheck_delivery_identity(None, "old", "a" * 64, "1", reference=None)
