"""Skip kernel-sandbox-dependent tests where Landlock is unavailable.

The EPUB inspection sandbox needs Landlock ABI >= 3. Runners whose kernel lacks
it cannot execute those tests; the application keeps preserved-file processing
disabled there as well. This is a local-development convenience: CI sets
LIBRARIUM_REQUIRE_LANDLOCK=1, which makes the absence a failure instead.
"""

import os
import pathlib

import pytest

_LANDLOCK_DEPENDENT = {
    "backend/tests/test_book_assessment.py",
    "backend/tests/test_book_check_jobs.py",
    "backend/tests/test_book_workspace.py",
    "backend/tests/test_delivery_identity.py",
    "backend/tests/test_duplicate_formats.py",
    "backend/tests/test_empty_navigation.py",
    "backend/tests/test_epub_inspection_regressions.py",
    "backend/tests/test_epub_source_positions.py",
    "backend/tests/test_epubcheck_native.py",
    "backend/tests/test_epubcheck_reports.py",
    "backend/tests/test_epubcheck_sandbox.py",
    "backend/tests/test_file_inspection_api.py",
    "backend/tests/test_file_inspections.py",
    "backend/tests/test_incoming_assessment.py",
    "backend/tests/test_inspection_process.py",
    "backend/tests/test_package_comparison.py",
    "backend/tests/test_python_sandbox.py",
    "backend/tests/test_reference_assessment.py",
    "backend/tests/test_sandbox_codec_aliases.py",
    "backend/tests/test_sandbox_codec_parity.py",
    "backend/tests/test_sandbox_prctl.py",
    "backend/tests/test_sandbox_preflight.py",
    "tests/test_epub_container_acceptance.py",
}


def _landlock_available():
    from librarium.epubcheck_sandbox import available

    return available()


def pytest_collection_modifyitems(config, items):
    if os.environ.get("LIBRARIUM_REQUIRE_LANDLOCK") or _landlock_available():
        return
    root = pathlib.Path(config.rootpath)
    marker = pytest.mark.skip(reason="Landlock ABI >= 3 unavailable on this kernel")
    for item in items:
        relative = pathlib.Path(item.fspath).resolve().relative_to(root).as_posix()
        if relative in _LANDLOCK_DEPENDENT:
            item.add_marker(marker)
