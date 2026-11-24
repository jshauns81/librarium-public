"""Synthetic populated-state adapter executed by each selected source/runtime.

The caller owns isolation, admission, source selection and process supervision.
This adapter uses application enqueue, worker and report owners without replacing
their engines. Its old-state receipt is never rewritten after migration.
"""

import argparse
import hashlib
import io
import json
import os
import sqlite3
import stat
import uuid
import zipfile
from contextlib import closing
from pathlib import Path


class FixtureRefusal(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise FixtureRefusal(reason)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def key(label):
    return uuid.uuid5(uuid.NAMESPACE_URL, "librarium-synthetic-upgrade-v1/" + label)


def source_bytes(generation):
    files = {
        "mimetype": "application/epub+zip",
        "META-INF/container.xml": '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        "book.opf": '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book">synthetic-upgrade</dc:identifier><dc:title>Synthetic upgrade fixture</dc:title><dc:language>en</dc:language></metadata><manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest><spine><itemref idref="chapter"/></spine></package>',
        "chapter.xhtml": '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Synthetic chapter</title></head><body><h1 id="start">1</h1><p>Synthetic retained text: '
        + generation
        + ".</p></body></html>",
        "nav.xhtml": '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Contents</title></head><body><nav epub:type="toc"><ol><li><a href="chapter.xhtml#start">1</a></li></ol></nav></body></html>',
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as book:
        for name, text in files.items():
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_STORED
            book.writestr(entry, text)
    return output.getvalue()


def artifact_inventory(root):
    root = Path(root)
    info = root.lstat()
    require(
        stat.S_ISDIR(info.st_mode)
        and stat.S_IMODE(info.st_mode) == 0o700
        and info.st_uid == os.geteuid(),
        "Artifact root custody differs",
    )
    files = {}
    for path in sorted(root.iterdir()):
        info = path.lstat()
        require(
            stat.S_ISREG(info.st_mode)
            and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_uid == os.geteuid(),
            "Artifact file custody differs",
        )
        files[path.name] = {
            "sha256": digest(path.read_bytes()),
            "size": info.st_size,
            "mode": stat.S_IMODE(info.st_mode),
            "uid": info.st_uid,
            "gid": info.st_gid,
        }
    root_info = root.stat()
    return {
        "root": {"mode": 0o700, "uid": root_info.st_uid, "gid": root_info.st_gid},
        "files": files,
    }


def verify_artifacts(root, retained, *, additional=False):
    actual = artifact_inventory(root)
    require(actual["root"] == retained["root"], "Artifact root ownership differs")
    require(
        set(retained["files"]) <= set(actual["files"])
        if additional
        else set(retained["files"]) == set(actual["files"]),
        "Artifact inventory differs",
    )
    require(
        all(actual["files"][name] == value for name, value in retained["files"].items()),
        "Retained artifact differs",
    )


def catalogue_fixture(root):
    from django.conf import settings
    from librarium.catalogue import CONTRACT

    root.mkdir(mode=0o700)
    version = "2026.01.01.1"
    path = root / f"{version}.sqlite"
    with closing(sqlite3.connect(path)) as db, db:
        for table, columns in sorted(CONTRACT.items()):
            db.execute(f"CREATE TABLE {table} ({','.join(sorted(columns))})")
        db.execute("INSERT INTO meta VALUES ('catalog_version', ?)", (version,))
        db.execute(
            "INSERT INTO work(id,title,type,first_published,synopsis) "
            "VALUES ('synthetic_upgrade','Synthetic upgrade fixture','novel','2001','Synthetic')"
        )
        db.execute("INSERT INTO author(id,name) VALUES (1,'Synthetic Author')")
        db.execute(
            "INSERT INTO work_author(work_id,author_id,role) "
            "VALUES ('synthetic_upgrade',1,'author')"
        )
        db.execute(
            "INSERT INTO edition(id,work_id,format,isbn13,publisher,release_date) "
            "VALUES ('synthetic_edition','synthetic_upgrade','ebook','9780306406157',"
            "'Synthetic Press','2001')"
        )
        db.execute(
            "INSERT INTO field_support(entity,entity_id,field,value,score,agree_json,disagree_json) "
            "VALUES ('work','synthetic_upgrade','title','Synthetic upgrade fixture',1,'[]','[]')"
        )
    (root / "current").write_text(version)
    settings.LIBRARIUM_CATALOGUE_DIR = str(root)
    settings.LIBRARIUM_CATALOGUE_FIXTURE = True
    return {
        "catalogue_work_id": "synthetic_upgrade",
        "version": version,
        "sha256": digest(path.read_bytes()),
    }


FIELDS = (
    "id",
    "kind",
    "target_id",
    "work_id",
    "request_key",
    "input_fingerprint",
    "input",
    "fixture_failure",
    "state",
    "checkpoint",
    "revision",
    "attempts",
    "lease_token",
    "lease_until",
    "message",
    "result",
    "created_at",
    "updated_at",
)


def row(job):
    from django.core.serializers.json import DjangoJSONEncoder

    return json.loads(
        json.dumps({name: getattr(job, name) for name in FIELDS}, cls=DjangoJSONEncoder)
    )


def projection(job):
    from librarium.views import job_data

    return job_data(job)


def complete(job):
    from django.core.management import call_command

    call_command("inspection_worker", once=True, step_seconds=0)
    job.refresh_from_db()
    require(job.state == "succeeded", "Selected runtime did not complete fixture work")
    require(job.attempts == 1 and job.checkpoint == 4, "Worker completion evidence differs")
    return job


def preserved_epub(generation):
    from librarium import artifacts, epub_validations, file_inspections

    source = source_bytes(generation)
    inspection = file_inspections.enqueue(
        io.BytesIO(source),
        key(generation + "/epub"),
        digest(source),
        "Synthetic upgrade fixture.epub",
        expected_size=len(source),
    )
    complete(inspection)
    require(
        artifacts.read("source", digest(source), len(source)) == source,
        "Preserved source differs from generated fixture",
    )
    structural = file_inspections.report(inspection)
    require(structural["report"]["inspection_complete"], "Structural inspection incomplete")
    require(structural["report"]["structural_check"] == "passed", "Structural fixture failed")
    validation = complete(epub_validations.enqueue(inspection.pk, key(generation + "/checker")))
    conformance = epub_validations.report(validation)
    # Missing dcterms:modified intentionally produces real conformance findings.
    require(conformance["report"]["outcome"] == "failed", "Expected native checker findings")
    require(conformance["report"]["counts"]["error"] > 0, "Missing native checker error evidence")
    require(conformance["report"]["process_exit_code"] == 1, "Checker did not finish normally")
    require(conformance["report"]["content_acceptance"] == "not_checked", "Scope differs")
    require(
        file_inspections.enqueue(
            io.BytesIO(source),
            key(generation + "/epub"),
            digest(source),
            "Synthetic upgrade fixture.epub",
            expected_size=len(source),
        ).pk
        == inspection.pk,
        "Inspection replay differs",
    )
    require(
        epub_validations.enqueue(inspection.pk, key(generation + "/checker")).pk == validation.pk,
        "Checker replay differs",
    )
    return {
        "rows": [row(inspection), row(validation)],
        "projections": [projection(inspection), projection(validation)],
        "reports": [structural, conformance],
        "generated_source_sha256": digest(source),
    }


def retired_history():
    """Retired work stays stored history after the upgrade: readable, and never run."""
    from django.core.management import call_command
    from librarium.models import Job
    from librarium.views import job_data

    job = Job.objects.create(
        kind="epub_correction",
        target_id=digest(b"synthetic retired review copy"),
        request_key=key("current/retired"),
        input={"title": "Synthetic retired review copy", "source_version": "retired"},
        input_fingerprint=digest(b"synthetic retired input"),
        message="Held for review",
    )
    stored = row(job)
    call_command("inspection_worker", once=True, step_seconds=0)
    job.refresh_from_db()
    require(row(job) == stored, "The current worker ran a retired job")
    shown = job_data(job)
    require(
        shown["retired"] is True
        and shown["kind"] == "epub_correction"
        and shown["state"] == "cancelled"
        and shown["stored_state"] == "queued"
        and shown["result"] == {},
        "A retired job does not read as plain history",
    )
    return {"row": stored, "projection": shown}


def save_receipt(path, value):
    with path.open("x", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def seed(path):
    from django.conf import settings
    from librarium import file_inspections
    from librarium.epub_inspection import POLICY_VERSION
    from librarium.models import Job
    from librarium.services import enqueue_catalogue

    require(not Job.objects.exists(), "Seed requires an empty disposable application database")
    require(POLICY_VERSION == "librarium.epub-structure.v5", "Historical runtime policy differs")
    pin = catalogue_fixture(path.parent / "catalogue")
    metadata = complete(enqueue_catalogue(pin, str(key("old/catalogue"))))
    require(
        enqueue_catalogue(pin, str(key("old/catalogue"))).pk == metadata.pk,
        "Metadata replay differs",
    )
    value = preserved_epub("old")
    value["rows"].insert(0, row(metadata))
    value["projections"].insert(0, projection(metadata))
    source = source_bytes("obsolete-pending")
    pending = file_inspections.enqueue(
        io.BytesIO(source),
        key("old/pending"),
        digest(source),
        "Synthetic pending fixture.epub",
        expected_size=len(source),
    )
    require(pending.state == "queued" and pending.attempts == 0, "Pending fixture already executed")
    value.update(
        schema="librarium.synthetic-upgrade-fixture.v1",
        provenance="sanitized-historical-source-schema",
        catalogue=pin,
        pending=row(pending),
        pending_scope="Genuine old-policy admission, deliberately unexecuted negative fixture",
        artifacts=artifact_inventory(Path(settings.LIBRARIUM_ARTIFACT_DIR)),
    )
    save_receipt(path, value)


def verify_retained(value, *, additional=False, pending_failed=False):
    from django.conf import settings
    from librarium import epub_validations, file_inspections
    from librarium.models import Job

    require(
        value["schema"] == "librarium.synthetic-upgrade-fixture.v1",
        "Fixture receipt schema differs",
    )
    verify_artifacts(
        Path(settings.LIBRARIUM_ARTIFACT_DIR), value["artifacts"], additional=additional
    )
    for expected, projected in zip(value["rows"], value["projections"], strict=True):
        job = Job.objects.get(pk=expected["id"])
        require(row(job) == expected, "Retained job evidence differs")
        require(projection(job) == projected, "Historical job projection differs")
    for expected in value["reports"]:
        job = Job.objects.get(pk=expected["job_id"])
        actual = (
            file_inspections.report(job) if job.kind == "epub" else epub_validations.report(job)
        )
        require(actual == expected, "Retained historical report projection differs")
    pending = Job.objects.get(pk=value["pending"]["id"])
    if pending_failed:
        actual = row(pending)
        require(
            all(
                actual[name] == value["pending"][name]
                for name in (
                    "id",
                    "kind",
                    "target_id",
                    "request_key",
                    "input",
                    "input_fingerprint",
                    "created_at",
                )
            ),
            "Obsolete pending captured input was rewritten",
        )
        require(
            pending.state == "failed" and pending.attempts == 1,
            "Obsolete pending work was not refused",
        )
        require(
            pending.message
            == "The preserved EPUB could not be inspected. No library changes were made.",
            "Unexpected obsolete-policy failure",
        )
        require(
            not pending.result.get("report_sha256"),
            "Obsolete policy unexpectedly published a report",
        )
    else:
        require(row(pending) == value["pending"], "Unexecuted historical fixture differs")


def verify_current(value):
    from django.core.management import call_command
    from librarium.epub_inspection import POLICY_VERSION

    require(
        POLICY_VERSION != "librarium.epub-structure.v5", "Candidate still uses historical policy"
    )
    verify_retained(value)
    from librarium import file_inspections
    from librarium.models import Job

    pending = Job.objects.get(pk=value["pending"]["id"])
    try:
        file_inspections._validate_input(
            pending.input, pending.input_fingerprint, pending.target_id
        )
    except file_inspections.InspectionError as exc:
        require(
            str(exc) == "The captured inspection policy is unavailable",
            "Unexpected policy preflight refusal",
        )
    else:
        raise FixtureRefusal("Obsolete policy preflight unexpectedly accepted")
    call_command("inspection_worker", once=True, step_seconds=0)
    verify_retained(value, pending_failed=True)


def work_current(path):
    from django.conf import settings
    from librarium.models import Job

    retained = json.loads(path.read_text())
    verify_retained(retained, additional=True, pending_failed=True)
    value = preserved_epub("current")
    value.update(
        schema="librarium.synthetic-upgrade-current.v1",
        pending_after=row(Job.objects.get(pk=retained["pending"]["id"])),
        retired=retired_history(),
        artifacts=artifact_inventory(Path(settings.LIBRARIUM_ARTIFACT_DIR)),
    )
    save_receipt(path.with_name("current-fixture.json"), value)
    verify_retained(retained, additional=True, pending_failed=True)


def verify_all(path):
    from django.conf import settings
    from librarium import epub_validations, file_inspections
    from librarium.models import Job

    retained = json.loads(path.read_text())
    verify_retained(retained, additional=True, pending_failed=True)
    current = json.loads(path.with_name("current-fixture.json").read_text())
    require(
        row(Job.objects.get(pk=retained["pending"]["id"])) == current["pending_after"],
        "Pending failure evidence changed",
    )
    require(
        current["schema"] == "librarium.synthetic-upgrade-current.v1",
        "Current receipt schema differs",
    )
    verify_artifacts(Path(settings.LIBRARIUM_ARTIFACT_DIR), current["artifacts"])
    retired = Job.objects.get(pk=current["retired"]["row"]["id"])
    require(
        row(retired) == current["retired"]["row"]
        and projection(retired) == current["retired"]["projection"],
        "Retired history differs",
    )
    for expected, projected in zip(current["rows"], current["projections"], strict=True):
        job = Job.objects.get(pk=expected["id"])
        require(
            row(job) == expected and projection(job) == projected,
            "Current retained evidence differs",
        )
    for expected in current["reports"]:
        job = Job.objects.get(pk=expected["job_id"])
        actual = (
            file_inspections.report(job) if job.kind == "epub" else epub_validations.report(job)
        )
        require(actual == expected, "Current retained report differs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "phase", choices=("seed", "verify-old", "verify-current", "work-current", "verify-all")
    )
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    require(
        os.environ.get("LIBRARIUM_UPGRADE_FIXTURE") == "1",
        "Explicit synthetic fixture scope required",
    )
    import django

    django.setup()
    if args.phase == "seed":
        seed(args.receipt)
    elif args.phase == "verify-old":
        verify_retained(json.loads(args.receipt.read_text()))
    elif args.phase == "verify-current":
        verify_current(json.loads(args.receipt.read_text()))
    elif args.phase == "work-current":
        work_current(args.receipt)
    else:
        verify_all(args.receipt)
    print(json.dumps({"phase": args.phase, "status": "passed"}, sort_keys=True))


if __name__ == "__main__":
    main()
