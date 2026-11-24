"""Fixture identity and custody checks must fail before accepting retained evidence."""

import hashlib
import io
import os
import zipfile

import pytest

from scripts import upgrade_fixture as fixture


def test_generated_epub_is_reproducible_and_explicitly_synthetic():
    before = fixture.source_bytes("old")
    assert before == fixture.source_bytes("old")
    assert (
        hashlib.sha256(before).hexdigest()
        != hashlib.sha256(fixture.source_bytes("current")).hexdigest()
    )
    with zipfile.ZipFile(io.BytesIO(before)) as book:
        assert "Synthetic upgrade fixture" in book.read("book.opf").decode()
        assert all(part.date_time == (1980, 1, 1, 0, 0, 0) for part in book.infolist())


def test_generated_catalogue_is_reproducible_and_admitted_by_real_capture(tmp_path, settings):
    from librarium.catalogue_reviews import capture_catalogue

    first = fixture.catalogue_fixture(tmp_path / "first")
    second = fixture.catalogue_fixture(tmp_path / "second")
    assert first == second
    captured = capture_catalogue(second["catalogue_work_id"], second["version"], second["sha256"])
    assert captured["fixture"] is True
    assert captured["title"] == "Synthetic upgrade fixture"
    assert captured["edition_count"] == 1
    assert captured["source_sha256"] == second["sha256"]


@pytest.mark.parametrize("change", ["bytes", "mode", "owner", "symlink", "extra", "missing"])
def test_changed_artifact_custody_is_refused(tmp_path, change):
    root = tmp_path / "artifacts"
    root.mkdir(mode=0o700)
    item = root / ("source-" + "a" * 64)
    item.write_bytes(b"retained synthetic source")
    item.chmod(0o600)
    retained = fixture.artifact_inventory(root)
    if change == "bytes":
        item.write_bytes(b"changed")
    elif change == "mode":
        item.chmod(0o644)
    elif change == "owner":
        retained["files"][item.name]["uid"] = os.geteuid() + 1
    elif change == "symlink":
        item.unlink()
        item.symlink_to(root / "absent")
    elif change == "extra":
        (root / "unexpected").write_bytes(b"extra")
    else:
        item.unlink()
    with pytest.raises(fixture.FixtureRefusal):
        fixture.verify_artifacts(root, retained)
