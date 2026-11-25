"""Synthetic EPUB acceptance inside the exact built image, using persistent app state."""

import ctypes
import hashlib
import io
import json
import os
import re
import stat
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from datetime import UTC, datetime

NAME = "CI synthetic EPUB.epub"
KEY = str(uuid.uuid5(uuid.NAMESPACE_URL, "librarium-container-epub-v1"))
VALIDATION_KEY = str(uuid.uuid5(uuid.NAMESPACE_URL, "librarium-container-epub-validation-v1"))


def source_bytes():
    files = {
        "mimetype": "application/epub+zip",
        "META-INF/container.xml": '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        "book.opf": '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book">synthetic-ci</dc:identifier><dc:title>Synthetic container fixture</dc:title><dc:language>en</dc:language></metadata><manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest><spine><itemref idref="chapter"/></spine></package>',
        "chapter.xhtml": '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Synthetic chapter</title></head><body><h1 id="start">1</h1><p>Original synthetic acceptance text.</p></body></html>',
        "nav.xhtml": '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title></head><body><nav epub:type="toc"><ol><li><a href="chapter.xhtml#start">1</a></li></ol></nav></body></html>',
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as zipped:
        for name, text in files.items():
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_STORED
            zipped.writestr(entry, text)
    return output.getvalue()


def request(path, data=None, csrf=None, *, validation=False):
    headers = {
        "Host": "lib.example.org",
        "X-Forwarded-Proto": "https",
        "Origin": "https://lib.example.org",
    }
    if data is not None:
        headers.update(
            {
                "Content-Type": "application/json" if validation else "application/epub+zip",
                "X-CSRFToken": csrf,
                "Cookie": f"librarium_csrftoken={csrf}",
                "Idempotency-Key": VALIDATION_KEY if validation else KEY,
            }
        )
        if not validation:
            headers["X-Source-SHA256"] = hashlib.sha256(data).hexdigest()
            headers["X-Source-Name"] = urllib.parse.quote(NAME, safe="")
    req = urllib.request.Request("http://127.0.0.1:8123" + path, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as response:
        assert response.status == (202 if data is not None else 200), response.status
        return json.load(response)


def check_report(envelope, digest, result):
    report = envelope["report"]
    assert envelope["source_sha256"] == digest
    assert re.fullmatch("[a-f0-9]{64}", envelope["report_sha256"])
    assert report["source_sha256"] == report["expected_sha256"] == digest
    assert report["inspection_complete"] is True
    assert report["structural_check"] == "passed", report["findings"]
    assert report["epubcheck"] == "not_run"
    assert report["content_acceptance"] == "not_checked"
    assert report["ready"] is False
    assert len(report["spine"]) == 1
    # The same script also drives the pinned released image, which may still inspect at v10.
    from librarium.epub_inspection import POLICY_VERSION

    version = report["policy"]["version"]
    assert version == POLICY_VERSION
    assert version in {"librarium.epub-structure.v10", "librarium.epub-structure.v11"}
    with zipfile.ZipFile(io.BytesIO(source_bytes())) as zipped:
        package_digest = hashlib.sha256(zipped.read("book.opf")).hexdigest()
    assert report["package"]["byte_sha256"] == package_digest
    evidence = report["identifier_evidence"]
    assert evidence["schema_version"] == "librarium.epub-identifiers.v1"
    assert evidence["package_path"] == report["package"]["path"] == "book.opf"
    assert evidence["package_sha256"] == package_digest
    assert evidence["package_version"] == "3.0"
    assert evidence["unique_identifier"] == "book" and evidence["prefix"] is None
    assert evidence["entries"] == [
        {
            "source_index": 2,
            "value": "synthetic-ci",
            "id": "book",
            "xml_id": None,
            "id_count": 1,
            "xml_id_count": 0,
            "opf_scheme": None,
            "text_only": True,
        }
    ]
    assert evidence["refinements"] == []
    attribution = report["source_attribution"]
    assert attribution["policy"] == "librarium.epub-source-attribution.v1"
    assert attribution["source_sha256"] == digest
    # This fixture has a plain heading, not an explicitly marked title page.
    assert attribution["status"] == "recorded"
    assert attribution["observations"][0]["rule"] == "front_matter_lead"
    assert attribution["observations"][0]["scope"] == "unclassified"
    assert attribution["observations"][0]["title"]["text"] == "1"
    content = report["content_evidence"]
    assert content["policy"] == "librarium.epub-content-evidence.v2"
    assert content["status"] == "recorded" and content["reason"] is None
    assert content["source_sha256"] == digest
    text = "1 Original synthetic acceptance text."
    assert content["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert content["text_chars"] == len(text) and content["spine_documents"] == 1
    with zipfile.ZipFile(io.BytesIO(source_bytes())) as zipped:
        chapter_bytes = zipped.read("chapter.xhtml")
    framed = len(chapter_bytes).to_bytes(8, "big") + chapter_bytes
    assert content["spine_bytes_sha256"] == hashlib.sha256(framed).hexdigest()
    document_text = report["document_text_evidence"]
    assert document_text["policy"] == "librarium.epub-document-text.v2"
    assert document_text["status"] == "recorded" and document_text["reason"] is None
    assert document_text["source_sha256"] == digest
    assert document_text["documents"] == [
        {
            "path": "chapter.xhtml",
            "spine_index": 0,
            "resource_sha256": hashlib.sha256(chapter_bytes).hexdigest(),
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "text_chars": len(text),
        }
    ]

    assert result["source_sha256"] == digest
    assert result["source_version"] == report["policy"]["version"]
    assert result["policy"] == report["policy"]
    assert result["report_sha256"] == envelope["report_sha256"]
    chapter = next(item for item in report["documents"] if item["path"] == "chapter.xhtml")
    assert chapter["headings"][0]["label"] == "1"
    assert report["navigation"]["entries"] == [
        {
            "path": "nav.xhtml",
            "target_path": "chapter.xhtml",
            "fragment": "start",
            "label": "1",
            "kind": "nav",
            "ancestors": [],
        }
    ]
    if version == "librarium.epub-structure.v10":
        assert report["contents_plan"]["inspection_policy"] == version
        return
    # Inspection v11 no longer plans contents (L091): a table of contents is checked, not rebuilt.
    assert "contents_plan" not in report and "contents_observations" not in report
    assert all("blocks" not in item for item in report["documents"])
    assert "contents_plan" not in result


def check_validation(envelope, source, validation, digest, source_size):
    result, report = validation["result"], envelope["report"]
    assert validation["kind"] == "epub_validation"
    assert validation["state"] == "succeeded", validation
    assert envelope["job_id"] == validation["id"]
    assert envelope["source_job_id"] == result["source_job_id"] == source["id"]
    assert (
        envelope["source_report_sha256"]
        == result["source_report_sha256"]
        == source["result"]["report_sha256"]
    )
    assert envelope["source_sha256"] == report["source_sha256"] == result["source_sha256"] == digest
    assert envelope["report_sha256"] == result["report_sha256"]
    assert re.fullmatch("[a-f0-9]{64}", envelope["report_sha256"])
    assert report["source_size"] == result["source_size"] == source_size
    assert report["schema_version"] == "librarium.epub-validation.v1"
    assert report["policy"] == result["policy"]
    assert report["policy"]["version"] == result["source_version"]
    assert report["validator"] == result["validator"]
    assert report["validator"]["name"] == "EPUBCheck"
    assert report["validator"]["version"] == "5.4.0"
    assert report["validator"]["java_major"] == 21
    for name in (
        "outcome",
        "counts",
        "messages_truncated",
        "message_repetition_limit",
        "process_exit_code",
        "ready",
        "content_acceptance",
    ):
        assert result[name] == report[name], name
    # This preserved fixture deliberately lacks the required dcterms:modified metadata.
    assert report["outcome"] == "failed"
    assert report["process_exit_code"] == 1
    assert report["counts"]["fatal"] == 0
    assert report["counts"]["error"] > 0
    assert report["counts"]["info"] is None
    assert any(
        item["id"] == "RSC-005"
        and item["severity"] == "ERROR"
        and any(location["path"] == "book.opf" for location in item["locations"])
        for item in report["messages"]
    )
    assert report["ready"] is False
    assert report["content_acceptance"] == "not_checked"


def validate_source(source, csrf):
    path = f"/api/epub-inspections/{source['id']}/validations"
    first = request(path, b"{}", csrf, validation=True)
    replay = request(path, b"{}", csrf, validation=True)
    assert first["id"] == replay["id"]
    for _ in range(400):
        job = request("/api/jobs/" + first["id"])
        assert request("/api/health") == {"status": "ready"}
        if job["state"] in {"succeeded", "failed", "cancelled"}:
            assert job["state"] == "succeeded", job
            break
        time.sleep(0.25)
    else:
        raise AssertionError("Independent worker did not finish bounded EPUBCheck validation")
    recovered = request(path + "?request_key=" + VALIDATION_KEY)
    assert recovered["id"] == first["id"]
    check_validation(
        request(f"/api/epub-validations/{recovered['id']}/report"),
        source,
        recovered,
        hashlib.sha256(source_bytes()).hexdigest(),
        len(source_bytes()),
    )


def native_checks():
    from librarium.epubcheck_process import VALIDATION_POLICY, VALIDATOR_IDENTITY, validate_isolated

    with zipfile.ZipFile(io.BytesIO(source_bytes())) as zipped:
        parts = {name: zipped.read(name) for name in zipped.namelist()}
    parts["book.opf"] = parts["book.opf"].replace(
        b"</metadata>", b'<meta property="dcterms:modified">2026-10-27T00:00:00Z</meta></metadata>'
    )

    def packed():
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as zipped:
            for name, body in parts.items():
                zipped.writestr(name, body)
        return output.getvalue()

    for warning in (False, True):
        if warning:
            parts["book.opf"] = parts["book.opf"].replace(b">synthetic-ci<", b">urn:uuid:bogus<")
        data = packed()
        report = validate_isolated(
            data, hashlib.sha256(data).hexdigest(), VALIDATION_POLICY, VALIDATOR_IDENTITY
        )
        assert report["outcome"] == "passed" and report["process_exit_code"] == 0
        assert report["counts"]["fatal"] == report["counts"]["error"] == 0
        assert report["counts"]["warning"] == int(warning)
        assert report["counts"]["info"] is None
    with tempfile.TemporaryDirectory(prefix="librarium-checker-sentinel-") as temporary:
        sentinel = Path(temporary) / "owned.dtd"
        sentinel.write_text("<!ELEMENT package ANY>")
        parts["book.opf"] = (
            f'<!DOCTYPE package SYSTEM "{sentinel.as_uri()}">'.encode() + parts["book.opf"]
        )
        library = ctypes.CDLL(None)
        library.inotify_init1.argtypes = [ctypes.c_int]
        library.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        descriptor = library.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        assert descriptor >= 0
        try:
            assert library.inotify_add_watch(descriptor, os.fsencode(sentinel), 0x21) >= 0
            data = packed()
            report = validate_isolated(
                data, hashlib.sha256(data).hexdigest(), VALIDATION_POLICY, VALIDATOR_IDENTITY
            )
            assert report["outcome"] == "failed" and report["ready"] is False
            try:
                observed = os.read(descriptor, 4096)
            except BlockingIOError:
                observed = b""
            assert not observed, "The checker opened an external document"
        finally:
            os.close(descriptor)
    print("PASS: actual valid/warning-only conformance and external-document file denial")


def create():
    source = source_bytes()
    session = request("/api/session")
    assert session["file_inspections"] is True
    first = request("/api/epub-inspections", source, session["csrf"])
    replay = request("/api/epub-inspections", source, session["csrf"])
    assert first["id"] == replay["id"]
    assert first["kind"] == "epub"
    for _ in range(80):
        job = request("/api/jobs/" + first["id"])
        assert request("/api/health") == {"status": "ready"}
        if job["state"] in {"succeeded", "failed", "cancelled"}:
            assert job["state"] == "succeeded", job["message"]
            break
        time.sleep(0.25)
    else:
        raise AssertionError("Independent worker did not inspect the preserved EPUB")
    recovered = request("/api/epub-inspections?request_key=" + KEY)
    assert recovered["id"] == first["id"]
    check_report(
        request(f"/api/epub-inspections/{first['id']}/report"),
        hashlib.sha256(source).hexdigest(),
        recovered["result"],
    )
    validate_source(recovered, session["csrf"])
    native_checks()
    print(
        "PASS: preserved source, inspection and explicit EPUBCheck validation, replay and immutable reports"
    )


def verify():
    job = request("/api/epub-inspections?request_key=" + KEY)
    assert job["state"] == "succeeded"
    check_report(
        request(f"/api/epub-inspections/{job['id']}/report"),
        hashlib.sha256(source_bytes()).hexdigest(),
        job["result"],
    )
    validation = request(
        f"/api/epub-inspections/{job['id']}/validations?request_key=" + VALIDATION_KEY
    )
    check_validation(
        request(f"/api/epub-validations/{validation['id']}/report"),
        job,
        validation,
        hashlib.sha256(source_bytes()).hexdigest(),
        len(source_bytes()),
    )
    print("PASS: inspection and validation bindings survived web/worker replacement")


def backup():
    root = Path(os.environ["LIBRARIUM_ARTIFACT_DIR"])
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
        for path in sorted(root.iterdir()):
            if re.fullmatch("(?:source|report|corrected)-[a-f0-9]{64}", path.name):
                assert stat.S_ISREG(path.lstat().st_mode)
                archive.add(path, arcname=path.name, recursive=False)


def recovery_directory():
    return Path(os.environ.get("LIBRARIUM_ACCEPTANCE_RECOVERY_DIR", os.environ["LIBRARIUM_ARTIFACT_DIR"]))


def read_recovery_marker(name):
    from librarium.delivery_recovery import load, private_root, read_private
    root = private_root(recovery_directory())
    try:
        return load(read_private(root, name, 4096))
    finally:
        os.close(root)


def recovery_capture():
    from librarium.build_identity import load_build_identity
    from librarium.delivery_recovery import private_root, write_new
    from librarium.recovery_evidence import identity_binding, utc_text
    identity = load_build_identity()
    if os.environ.get("LIBRARIUM_REQUIRE_PACKAGED_IDENTITY") == "1":
        assert identity is not None, "packaged_build_identity_missing"
    marker = {"schema": "librarium.recovery-capture.v1",
              "captured_at": utc_text(datetime.now(UTC)), "binding": identity_binding(identity)}
    root = private_root(recovery_directory())
    try:
        write_new(root, "recovery-capture.json", marker)
    finally:
        os.close(root)


def recovery_start():
    from librarium.delivery_recovery import private_root, write_new
    from librarium.recovery_evidence import utc_text
    capture = read_recovery_marker("recovery-capture.json")
    assert set(capture) == {"schema", "captured_at", "binding"}
    assert capture["schema"] == "librarium.recovery-capture.v1"
    marker = {"schema": "librarium.recovery-clock.v1", "capture": capture,
              "started_at": utc_text(datetime.now(UTC)), "monotonic": time.monotonic()}
    root = private_root(recovery_directory())
    try:
        write_new(root, "recovery-clock.json", marker)
    finally:
        os.close(root)


def retained_recovery():
    from librarium.build_identity import load_build_identity
    from librarium.recovery_evidence import identity_binding, make_receipt, retain_receipt, timestamp, report_recovery
    marker = read_recovery_marker("recovery-clock.json")
    assert set(marker) == {"schema", "capture", "started_at", "monotonic"}
    assert marker["schema"] == "librarium.recovery-clock.v1"
    capture = marker["capture"]
    assert set(capture) == {"schema", "captured_at", "binding"}
    assert capture["schema"] == "librarium.recovery-capture.v1"
    identity = load_build_identity()
    assert capture["binding"] == identity_binding(identity), "restore_build_binding_changed"
    if os.environ.get("LIBRARIUM_REQUIRE_PACKAGED_IDENTITY") == "1":
        assert identity is not None, "packaged_build_identity_missing"
    assert type(marker["monotonic"]) in {float, int}
    receipt = make_receipt(
        "isolated_epub_database_artifacts", timestamp(capture["captured_at"]),
        timestamp(marker["started_at"]), datetime.now(UTC),
        time.monotonic() - marker["monotonic"], capture["binding"],
    )
    path = recovery_directory() / "recovery-rehearsal.json"
    retain_receipt(path, receipt)
    assert report_recovery(path, identity)["state"] == ("recorded" if identity else "incomplete")
    os.environ["LIBRARIUM_RECOVERY_RECEIPT"] = str(path)
    from django.core.management import call_command
    output = io.StringIO()
    call_command("support_report", stdout=output)
    support = json.loads(output.getvalue())
    assert support["database"]["state"] == "available"
    assert support["jobs"]["state"] == "observed"
    assert support["storage"]["artifacts"]["state"] == "observed"
    assert support["schema_compatibility"]["state"] == "compatible"
    assert support["build"]["state"] == ("known" if identity else "unknown")
    assert support["build"]["running_image_digest"] is None
    assert support["build"]["running_image_state"] == "unknown"
    assert support["recovery"]["state"] == ("recorded" if identity else "incomplete")
    if identity:
        assert support["build"]["source_sha256"] == identity["source_sha256"]
        assert support["build"]["compatibility"] == identity["compatibility"]
        assert support["build"]["runtime_compatibility_state"] == "compatible"
    print(json.dumps(receipt, sort_keys=True))
    return receipt


def restore():
    os.environ.setdefault("LIBRARIUM_ACCEPTANCE_RECOVERY_DIR", os.environ["LIBRARIUM_ARTIFACT_DIR"])
    with tempfile.TemporaryDirectory(prefix="librarium-artifact-restore-") as root:
        with tarfile.open(os.environ.get("LIBRARIUM_ACCEPTANCE_RESTORE_ARCHIVE", "/restore.tar"), "r") as archive:
            archive.extractall(root, filter="data")
        os.environ["LIBRARIUM_ARTIFACT_DIR"] = root
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "librarium.settings")
        import django

        django.setup()
        from librarium import artifacts, epub_validations, file_inspections
        from librarium.models import Job

        job = Job.objects.get(request_key=KEY, kind="epub")
        source = source_bytes()
        digest = hashlib.sha256(source).hexdigest()
        assert job.target_id == digest
        assert artifacts.read("source", digest, len(source)) == source
        check_report(file_inspections.report(job), digest, job.result)
        validation = Job.objects.get(request_key=VALIDATION_KEY, kind="epub_validation")
        check_validation(
            epub_validations.report(validation),
            {"id": str(job.pk), "result": job.result},
            {
                "id": str(validation.pk),
                "kind": validation.kind,
                "state": validation.state,
                "result": validation.result,
            },
            digest,
            len(source),
        )
        retained_recovery()
        print(
            "PASS: isolated database/artifact restore retains source, inspection and validation bindings"
        )


if __name__ == "__main__":
    modes = {"create": create, "verify": verify, "backup": backup, "restore": restore, "recovery-capture": recovery_capture, "recovery-start": recovery_start}
    modes[sys.argv[1]]()
