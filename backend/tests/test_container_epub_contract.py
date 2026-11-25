"""Exercise the exact-image synthetic report assertions on the current parser policy."""

import hashlib
import runpy
from copy import deepcopy
from pathlib import Path

import pytest
from librarium.epub_inspection import inspect_bytes


@pytest.fixture
def contract_report():
    contract = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / ".github/scripts/epub_container_acceptance.py")
    )
    data = contract["source_bytes"]()
    digest = hashlib.sha256(data).hexdigest()
    report = inspect_bytes(data, digest)
    envelope = {"source_sha256": digest, "report_sha256": "a" * 64, "report": report}
    result = {
        "source_sha256": digest,
        "source_version": report["policy"]["version"],
        "policy": report["policy"],
        "report_sha256": envelope["report_sha256"],
    }
    return contract, envelope, digest, result


def test_container_contract_accepts_the_current_complete_policy(contract_report):
    contract, envelope, digest, result = contract_report
    contract["check_report"](envelope, digest, result)


@pytest.mark.parametrize("field", ["source_sha256", "text_sha256", "spine_bytes_sha256"])
def test_container_contract_checks_source_content_fingerprints(contract_report, field):
    contract, envelope, digest, result = contract_report
    envelope = deepcopy(envelope)
    envelope["report"]["content_evidence"][field] = "0" * 64
    with pytest.raises(AssertionError):
        contract["check_report"](envelope, digest, result)
