"""The standalone proof must refuse unrelated targets and preserve its synthetic originals."""

import importlib.util
import io
import json
import sqlite3
import subprocess
import sys
import zipfile
from contextlib import closing
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/scripts/assessment_arm_acceptance.py"


@pytest.fixture
def proof():
    spec = importlib.util.spec_from_file_location("assessment_arm_proof", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prepare_refuses_existing_content_and_symlinks_without_touching_them(proof, tmp_path):
    root = tmp_path / "existing"
    root.mkdir()
    sentinel = root / "original.epub"
    sentinel.write_bytes(b"untouched")
    with pytest.raises(proof.ProofError):
        proof.prepare(root)
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(proof.ProofError):
        proof.prepare(link)
    assert sentinel.read_bytes() == b"untouched"
    assert list(root.iterdir()) == [sentinel]


def test_fixture_is_self_contained_readonly_and_has_no_runtime_credential_configuration(
    proof, tmp_path
):
    root = tmp_path / "proof"
    fixture = proof.prepare(root)
    before = proof.source_hashes(root)
    with closing(
        sqlite3.connect(f"file:{root / 'library/metadata.db'}?mode=ro&immutable=1", uri=True)
    ) as db:
        assert db.execute("SELECT uuid FROM library_id").fetchone()[0] == fixture["library_uuid"]
        assert db.execute("SELECT count(*) FROM books").fetchone()[0] == 2
        assert db.execute("SELECT format FROM data ORDER BY id").fetchall() == [
            ("EPUB",),
            ("EPUB",),
            ("PDF",),
        ]
    with closing(
        sqlite3.connect(
            f"file:{root / 'catalogue' / (proof.VERSION + '.sqlite')}?mode=ro&immutable=1", uri=True
        )
    ) as db:
        assert db.execute("SELECT id,title FROM work").fetchone() == (proof.WORK, proof.TITLE)
        assert db.execute("SELECT id,work_id,format FROM edition").fetchone() == (
            proof.EDITION,
            proof.WORK,
            "epub",
        )
    assert proof.load_fixture(root)[1] == fixture
    assert proof.source_hashes(root) == before
    assert all(not (root / name).stat().st_mode & 0o222 for name in before)
    configured = json.loads((root / "environment.json").read_text())
    unconfigured = json.loads((root / "environment-unconfigured.json").read_text())
    assert (
        configured["LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256"]
        == fixture["reference"]["registry_sha256"]
    )
    assert (
        unconfigured["LIBRARIUM_CONTENT_TRUST_REGISTRY"]
        == unconfigured["LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256"]
        == ""
    )
    assert not any("SECRET" in key or key.startswith("PG") for key in configured)
    with pytest.raises(proof.ProofError):
        proof.prepare(root)
    assert proof.source_hashes(root) == before


def test_source_variants_retain_one_document_text_match_after_markup_changes(proof):
    original, changed = proof.source_bytes(), proof.source_bytes(changed=True)
    assert original != changed
    with (
        zipfile.ZipFile(io.BytesIO(original)) as first,
        zipfile.ZipFile(io.BytesIO(changed)) as second,
    ):
        for name in ("first.xhtml", "second.xhtml"):
            first_raw, second_raw = first.read(name), second.read(name)
            assert first_raw != second_raw
            normalized = []
            for raw in (first_raw, second_raw):
                body = ET.fromstring(raw).find("{http://www.w3.org/1999/xhtml}body")
                normalized.append(" ".join("".join(body.itertext()).split()))
            assert (normalized[0] == normalized[1]) is (name == "first.xhtml")
    assert proof.source_bytes() == original


@pytest.mark.parametrize("mutation", ["bytes", "extra", "symlink", "oversize"])
def test_original_change_or_extra_file_prevents_acceptance_before_network(
    proof, tmp_path, mutation
):
    root = tmp_path / "proof"
    proof.prepare(root)
    target = root / "inputs/original.epub"
    if mutation == "extra":
        (root / "inputs/unexpected").write_bytes(b"extra")
    elif mutation == "symlink":
        target.unlink()
        target.symlink_to(root / "inputs/changed.epub")
    else:
        target.chmod(0o600)
        if mutation == "bytes":
            target.write_bytes(b"changed")
        else:
            with target.open("wb") as stream:
                stream.truncate(proof.MAX_FILE + 1)
    with pytest.raises(proof.ProofError):
        proof.load_fixture(root)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8123",
        "http://example.org:8123",
        "http://localhost:8123",
        "http://192.0.2.1:8123",
        "http://127.0.0.1",
        "http://" + "user@127.0.0.1:8123",
        "http://127.0.0.1:8123/api",
        "http://127.0.0.1:8123?target=x",
        "http://127.0.0.1:8123#fragment",
        "http://127.0.0.1:99999",
    ],
)
def test_target_origin_is_explicit_loopback_without_redirectable_components(proof, url):
    with pytest.raises(proof.ProofError):
        proof.Client(url)


def test_redirects_are_refused_without_forwarding_session_headers(proof):
    with pytest.raises(proof.ProofError):
        proof.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "http://example.org")


@pytest.mark.parametrize("mismatch", ["library", "catalogue", "work"])
def test_mismatched_server_identity_cannot_queue_work(proof, tmp_path, monkeypatch, mismatch):
    root = tmp_path / "proof"
    fixture = proof.prepare(root)
    calls = []

    class OtherServer:
        def __init__(self, _url):
            pass

        def request(self, path, data=None, **_kwargs):
            calls.append((path, data))
            assert data is None, "An unrelated target received a mutation"
            if path == "/api/session":
                return {"csrf": "synthetic", "direct_library": True, "file_inspections": True}
            if path == "/api/direct-library":
                return {
                    "total": 2,
                    "inventory": {
                        "library_uuid": "other"
                        if mismatch == "library"
                        else fixture["library_uuid"]
                    },
                }
            if path == "/api/catalogue":
                return {**fixture["catalogue"], "fixture": mismatch != "catalogue"}
            return {
                "id": proof.WORK,
                "title": "Other" if mismatch == "work" else proof.TITLE,
                "snapshot": {**fixture["catalogue"], "fixture": True},
            }

    monkeypatch.setattr(proof, "Client", OtherServer)
    with pytest.raises(proof.ProofError):
        proof.check(root, "http://127.0.0.1:8123")
    assert calls and all(body is None for _, body in calls)


def test_prepare_cli_does_not_claim_runtime_acceptance_or_print_private_root(tmp_path):
    root = tmp_path / "proof"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "prepare", "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("PREPARED:") and "no runtime check performed" in result.stdout
    assert "PASS:" not in result.stdout
    assert str(root) not in result.stdout + result.stderr
    assert not list(root.glob("check-result-*.json"))


@pytest.fixture
def loopback():
    """A tiny loopback API that answers each path with a fixed status and JSON body."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    replies = {"/ok": (200, {"state": "ok"}), "/refused": (409, {"error": "conflict"})}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, body = replies[self.path]
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_expected_refusals_are_evidence_and_unexpected_statuses_stop(proof, loopback):
    client = proof.Client(loopback)
    assert client.request("/refused", expected=409) == {"error": "conflict"}
    assert client.request("/ok", expected=proof.ACCEPTED) == {"state": "ok"}
    with pytest.raises(proof.ProofError):
        client.request("/refused")
    with pytest.raises(proof.ProofError):
        client.request("/ok", expected=409)


def identity_server(proof, fixture, calls, jobs):
    """A matching synthetic server whose check queue answers from `jobs`."""

    class Server:
        def __init__(self, _url):
            self.csrf = None

        def request(self, path, data=None, **kwargs):
            calls.append((path, data, kwargs.get("key")))
            if path == "/api/session":
                return {"csrf": "synthetic", "direct_library": True, "file_inspections": True}
            if path == "/api/direct-library":
                return {"total": 2, "inventory": {"library_uuid": fixture["library_uuid"]}}
            if path == "/api/catalogue":
                return {**fixture["catalogue"], "fixture": True}
            if path.startswith("/api/catalogue/works/"):
                return {
                    "id": proof.WORK,
                    "title": proof.TITLE,
                    "snapshot": {**fixture["catalogue"], "fixture": True},
                }
            return jobs.pop(0)

    return Server


def test_queue_control_requires_a_completed_api_check_before_any_mutation(
    proof, tmp_path, monkeypatch
):
    root = tmp_path / "proof"
    fixture = proof.prepare(root)
    calls = []
    monkeypatch.setattr(proof, "Client", identity_server(proof, fixture, calls, []))
    with pytest.raises(proof.ProofError):
        proof.queue_start(root, "http://127.0.0.1:8123", idle_seconds=0)
    assert calls and all(data is None for _, data, _ in calls)


def test_queue_control_refuses_an_attached_worker_without_cancelling(proof, tmp_path, monkeypatch):
    root = tmp_path / "proof"
    fixture = proof.prepare(root)
    route = "/api/epub-inspections/00000000-0000-4000-8000-000000000001/checks"
    (root / "check-result-inputs.json").write_bytes(
        proof.encoded({"route": route, "body": {"synthetic": True}})
    )
    calls = []
    jobs = [{"id": "job", "state": "queued"}, {"id": "job", "state": "running"}]
    monkeypatch.setattr(proof, "Client", identity_server(proof, fixture, calls, jobs))
    with pytest.raises(proof.ProofError):
        proof.queue_start(root, "http://127.0.0.1:8123", idle_seconds=0)
    mutations = [(path, data) for path, data, _ in calls if data is not None]
    assert mutations == [(route, {"synthetic": True})]
    assert not any(path.startswith("/api/jobs/") for path, _, _ in calls)
    assert not (root / "queue-pending.json").exists()


def test_check_cli_reports_fixed_failure_reason_without_private_root(tmp_path):
    root = tmp_path / "proof"
    subprocess.run(
        [sys.executable, str(SCRIPT), "prepare", "--root", str(root)],
        check=True,
        capture_output=True,
    )
    (root / "inputs/unexpected").write_bytes(b"extra")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "check",
            "--root",
            str(root),
            "--base-url",
            "http://127.0.0.1:9",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Synthetic originals changed before acceptance" in result.stderr
    assert "PASS:" not in result.stdout
    assert str(root) not in result.stdout + result.stderr
