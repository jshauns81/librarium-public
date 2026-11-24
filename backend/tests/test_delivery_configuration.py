"""Every synthetic-only writer guard is a tested admission boundary."""

import json

import pytest
from librarium.delivery_writer import WriterError, configuration

UUID = "00000000-0000-4000-8000-0000000000aa"


def setup(tmp_path, marker=None):
    tmp_path.mkdir(mode=0o700, exist_ok=True)
    roots = {}
    for name in ("library", "state", "artifacts"):
        p = tmp_path / name
        p.mkdir(mode=0o700)
        roots[name] = p
    (roots["state"] / "config").mkdir(mode=0o700)

    def secret(name, data):
        p = tmp_path / name
        p.write_bytes(data)
        p.chmod(0o600)
        return p

    if marker is not False:
        m = roots["library"] / "librarium-synthetic-owner.json"
        m.write_text(
            json.dumps(
                marker
                or {
                    "schema": "librarium.synthetic-owner.v1",
                    "library_uuid": UUID,
                    "sole_owner": True,
                }
            )
        )
        m.chmod(0o600)
    env = {
        "LIBRARIUM_DELIVERY_ENABLED": "1",
        "LIBRARIUM_WRITER_SYNTHETIC_ONLY": "1",
        "LIBRARIUM_WRITER_LIBRARY_ROOT": str(roots["library"]),
        "LIBRARIUM_WRITER_STATE_DIR": str(roots["state"]),
        "LIBRARIUM_ARTIFACT_DIR": str(roots["artifacts"]),
        "LIBRARIUM_WRITER_TOKEN_FILE": str(secret("token", b"t" * 32)),
        "LIBRARIUM_DELIVERY_SIGNING_KEY_FILE": str(secret("signing", b"s" * 32)),
        "LIBRARIUM_WRITER_LIBRARY_UUID": UUID,
        "LIBRARIUM_WRITER_RUNTIME_SHA256": "a" * 64,
        "LIBRARIUM_WRITER_ARCHIVE": str(tmp_path / "archive"),
        "CALIBRE_CONFIG_DIRECTORY": str(roots["state"] / "config"),
    }
    return env, roots


@pytest.mark.parametrize(
    "change,code",
    [
        ("disabled", "writer_disabled"),
        ("not_synthetic", "synthetic_only_required"),
        ("missing", "writer_configuration_incomplete"),
        ("marker", "synthetic_owner_unconfirmed"),
        ("marker_uuid", "synthetic_owner_unconfirmed"),
        ("overlap", "writer_storage_overlap"),
        ("mode", "storage_unavailable"),
        ("pin", "runtime_pin_invalid"),
        ("keys", "separate_signing_key_required"),
        ("config", "isolated_calibre_configuration_required"),
        ("plugins", "isolated_calibre_configuration_required"),
    ],
)
def test_all_synthetic_configuration_refusals(tmp_path, change, code):
    env, roots = setup(tmp_path)
    assert configuration(env)
    if change == "disabled":
        env["LIBRARIUM_DELIVERY_ENABLED"] = "0"
    elif change == "not_synthetic":
        env["LIBRARIUM_WRITER_SYNTHETIC_ONLY"] = "0"
    elif change == "missing":
        del env["LIBRARIUM_WRITER_ARCHIVE"]
    elif change == "marker":
        (roots["library"] / "librarium-synthetic-owner.json").unlink()
    elif change == "marker_uuid":
        (roots["library"] / "librarium-synthetic-owner.json").write_text("{}")
    elif change == "overlap":
        env["LIBRARIUM_ARTIFACT_DIR"] = str(roots["library"])
    elif change == "mode":
        roots["library"].chmod(0o755)
    elif change == "pin":
        env["LIBRARIUM_WRITER_RUNTIME_SHA256"] = "invalid"
    elif change == "keys":
        env["LIBRARIUM_DELIVERY_SIGNING_KEY_FILE"] = env["LIBRARIUM_WRITER_TOKEN_FILE"]
    elif change == "config":
        env["CALIBRE_CONFIG_DIRECTORY"] = str(roots["library"])
    elif change == "plugins":
        plugins = roots["state"] / "config" / "plugins"
        plugins.mkdir()
        (plugins / "fixture.zip").write_bytes(b"synthetic")
    with pytest.raises(WriterError, match=code):
        configuration(env)


@pytest.mark.parametrize(
    "change",
    [
        "state_missing",
        "state_file",
        "state_symlink",
        "state_not_writable",
        "state_shared",
        "config_missing",
        "config_file",
        "config_symlink",
        "config_not_writable",
        "config_shared",
        "read_only",
    ],
)
def test_unusable_writer_state_refuses_before_calibre_starts(tmp_path, monkeypatch, change):
    import os

    from librarium.delivery_writer import writer_state

    env, roots = setup(tmp_path)
    state, config = roots["state"], roots["state"] / "config"
    assert writer_state(env) is None
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    if change == "state_missing":
        config.rmdir()
        state.rmdir()
    elif change == "state_file":
        config.rmdir()
        state.rmdir()
        state.write_bytes(b"")
    elif change == "state_symlink":
        config.rmdir()
        state.rmdir()
        (elsewhere / "config").mkdir(mode=0o700)
        state.symlink_to(elsewhere)
    elif change == "state_not_writable":
        state.chmod(0o500)
    elif change == "state_shared":
        state.chmod(0o750)
    elif change == "config_missing":
        config.rmdir()
    elif change == "config_file":
        config.rmdir()
        config.write_bytes(b"")
    elif change == "config_symlink":
        config.rmdir()
        config.symlink_to(elsewhere)
    elif change == "config_not_writable":
        config.chmod(0o500)
    elif change == "config_shared":
        config.chmod(0o750)
    elif change == "read_only":
        real = os.fstatvfs

        class ReadOnly:
            def __init__(self, fd):
                self.f_flag = real(fd).f_flag | os.ST_RDONLY

        monkeypatch.setattr(os, "fstatvfs", ReadOnly)
    try:
        for check in (writer_state, configuration):
            with pytest.raises(WriterError, match="writer_state_unavailable"):
                check(env)
        assert not config.is_dir() or not any(config.iterdir())
    finally:
        for path in (state, config):
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o700)


def test_writer_state_names_its_configuration_codes(tmp_path):
    from librarium.delivery_writer import writer_state

    env, roots = setup(tmp_path)
    del env["LIBRARIUM_WRITER_STATE_DIR"]
    with pytest.raises(WriterError, match="writer_configuration_incomplete"):
        writer_state(env)
    env, roots = setup(tmp_path / "other")
    env["CALIBRE_CONFIG_DIRECTORY"] = str(roots["library"])
    with pytest.raises(WriterError, match="isolated_calibre_configuration_required"):
        writer_state(env)
    assert WriterError("writer_state_unavailable").status == 503


@pytest.mark.parametrize("change", ["archive", "file", "added", "hardlink"])
def test_runtime_verifies_complete_distribution_before_execution(tmp_path, change):
    import io
    import os
    import tarfile
    from hashlib import sha256

    from scripts.run_delivery_writer import verify_runtime

    archive, root = tmp_path / "runtime.txz", tmp_path / "runtime"
    root.mkdir()
    with tarfile.open(archive, "w:xz") as stream:
        member = tarfile.TarInfo("program")
        member.size = 7
        stream.addfile(member, io.BytesIO(b"program"))
    (root / "program").write_bytes(b"program")
    pin = sha256(archive.read_bytes()).hexdigest()
    verify_runtime(archive, root, pin)
    if change == "archive":
        archive.write_bytes(b"changed")
    elif change == "file":
        (root / "program").write_bytes(b"changed")
    elif change == "added":
        (root / "unexpected.pth").write_bytes(b"added")
    elif change == "hardlink":
        os.link(root / "program", tmp_path / "link")
    with pytest.raises(RuntimeError, match="runtime_(archive|installation)_changed"):
        verify_runtime(archive, root, pin)


def test_writer_modules_import_only_the_standard_library():
    """The pinned Calibre runtime imports these modules without application packages."""
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    probe = (
        "import sys\n"
        "class Refuse:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in {'django'}:\n"
        "            raise ImportError(name)\n"
        "sys.meta_path.insert(0, Refuse())\n"
        f"sys.path.insert(0, {str(backend)!r})\n"
        "import librarium.delivery_writer, librarium.delivery_broker\n"
        "import librarium.delivery_native, librarium.delivery_contract\n"
    )
    subprocess.run([sys.executable, "-I", "-c", probe], check=True, timeout=30)
