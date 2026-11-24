"""Uploaded EPUB jobs bind immutable artifacts and an exact inspection policy."""

import threading
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta

from django.db import DatabaseError, IntegrityError, connections, transaction
from django.db.models.functions import Now

from librarium import artifacts
from librarium.epub_inspection import (
    ARCHIVE_READER,
    POLICY_VERSION,
    UPSTREAM_REVISION,
    UPSTREAM_SOURCE_SHA256,
    InspectionPolicy,
)
from librarium.identifier_evidence import validate_identifier_evidence
from librarium.inspection_process import inspect_isolated
from librarium.models import Job

MAX_SOURCE_BYTES = artifacts.MAX_SOURCE_BYTES
NATIVE_READER_POLICIES = {f"librarium.epub-structure.v{number}" for number in range(2, 11)}
HISTORICAL_POLICIES = {f"librarium.epub-structure.v{number}" for number in range(1, 10)}
PLANNED_POLICIES = {f"librarium.epub-structure.v{n}" for n in range(4, 11)}
HEARTBEAT_SECONDS = 2
LEASE_SECONDS = 10
SCOPE = (
    "Structural checks and a read-only contents proposal. "
    "EPUBCheck and content completeness were not checked. "
    "Raw ZIP metadata conformance was not checked. "
    "This result does not identify a work, establish ownership or authorize library changes."
)
UPSTREAM = {
    "repository": "https://github.com/jshauns81/library-finish.git",
    "revision": UPSTREAM_REVISION,
    "source": "bin/epub_content.py",
    "source_sha256": UPSTREAM_SOURCE_SHA256,
}


class InspectionError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def replay(key, digest, name, origin=None, book_uuid=None):
    existing = Job.objects.filter(request_key=key).first()
    if existing is None:
        return None
    if (
        existing.kind == "epub"
        and existing.target_id == digest
        and existing.input.get("source_sha256") == digest
        and existing.input.get("source_name") == name
        and existing.input.get("library_origin") == origin
        and (book_uuid is None or existing.input.get("library_book_uuid") == book_uuid)
    ):
        return existing
    raise InspectionError("This request key belongs to a different request")


def enqueue(stream, key, digest, name, expected_size=None, *, origin=None, book_uuid=None):
    from librarium.services import fingerprint

    existing = replay(key, digest, name, origin, book_uuid)
    if existing:
        return existing
    source = artifacts.ingest(
        stream, digest, max_bytes=MAX_SOURCE_BYTES, expected_size=expected_size
    )
    captured = {
        "kind": "epub",
        "title": name,
        "source_name": name,
        "source_sha256": digest,
        "source_size": source["size"],
        "source_version": POLICY_VERSION,
        "policy": {"version": POLICY_VERSION, "limits": asdict(InspectionPolicy())},
        "upstream": UPSTREAM,
        "archive_reader": dict(ARCHIVE_READER),
        **({"library_origin": deepcopy(origin)} if origin is not None else {}),
        **({"library_book_uuid": book_uuid} if book_uuid is not None else {}),
    }
    try:
        with transaction.atomic():
            existing = replay(key, digest, name, origin, book_uuid)
            if existing:
                return existing
            job = Job.objects.create(
                kind="epub",
                target_id=digest,
                work=None,
                request_key=key,
                input=captured,
                input_fingerprint=fingerprint(captured),
            )
    except IntegrityError:
        existing = replay(key, digest, name, origin, book_uuid)
        if existing:
            return existing
        raise InspectionError(
            "This source already has an active inspection; refresh its progress"
        ) from None
    return job


def _running(job_id, token):
    return Job.objects.filter(
        pk=job_id, kind="epub", state="running", lease_token=token, lease_until__gt=Now()
    )


@transaction.atomic
def _prepare(job_id, token):
    job = _running(job_id, token).select_for_update().first()
    if job is None:
        return None
    job.checkpoint = 1
    job.message = "Checking the preserved EPUB"
    job.revision += 1
    job.save()
    return deepcopy(job.input), job.input_fingerprint, job.target_id


def renew(job_id, token):
    return bool(
        _running(job_id, token).update(lease_until=Now() + timedelta(seconds=LEASE_SECONDS))
    )


@contextmanager
def _heartbeat(job_id, token, *, renew_lease=None):
    stop = threading.Event()
    lost = threading.Event()

    def run():
        database = connections["default"]
        database.settings_dict = {
            **database.settings_dict,
            "OPTIONS": {**database.settings_dict.get("OPTIONS", {}), "connect_timeout": 2},
        }
        try:
            with database.cursor() as cursor:
                cursor.execute("SET lock_timeout = '1s'")
                cursor.execute("SET statement_timeout = '2s'")
            while not stop.wait(HEARTBEAT_SECONDS):
                if not (renew_lease or renew)(job_id, token):
                    lost.set()
                    return
        except DatabaseError:
            lost.set()
        finally:
            database.close()

    thread = threading.Thread(target=run, name=f"epub-lease-{job_id}", daemon=True)
    thread.start()
    try:
        yield lost
    finally:
        stop.set()
        thread.join()


def _validate_input(value, bound_fingerprint, target, *, historical=False):
    from librarium.services import fingerprint

    version = value.get("source_version")
    supported = version == POLICY_VERSION or (historical and version in HISTORICAL_POLICIES)
    if (
        fingerprint(value) != bound_fingerprint
        or value.get("kind") != "epub"
        or value.get("source_sha256") != target
        or not supported
        or version in NATIVE_READER_POLICIES
        and value.get("archive_reader") != ARCHIVE_READER
        or value.get("upstream") != UPSTREAM
        or not isinstance(value.get("policy"), dict)
        or value["policy"].get("version") != version
        or not isinstance(value["policy"].get("limits"), dict)
        or set(value["policy"]["limits"]) != set(asdict(InspectionPolicy()))
    ):
        raise InspectionError("The captured inspection policy is unavailable")
    try:
        return InspectionPolicy(**value["policy"]["limits"])
    except TypeError, ValueError:
        raise InspectionError("The captured inspection policy is unavailable") from None


def _validate_report(value, captured):
    if (
        value.get("schema_version") != "librarium.epub-inspection.v1"
        or value.get("source_sha256") != captured["source_sha256"]
        or value.get("expected_sha256") != captured["source_sha256"]
        or value.get("policy") != captured["policy"]
        or value.get("upstream") != captured["upstream"]
        or captured["source_version"] in NATIVE_READER_POLICIES
        and value.get("archive_reader") != captured.get("archive_reader")
        or value.get("structural_check") not in {"passed", "failed"}
        or type(value.get("inspection_complete")) is not bool
        or value.get("epubcheck") != "not_run"
        or value.get("content_acceptance") != "not_checked"
        or value.get("ready") is not False
    ):
        raise InspectionError("The report does not match its preserved source and policy")
    try:
        from librarium.content_evidence import INSPECTION_POLICIES, validate_content_evidence

        if captured["source_version"] in INSPECTION_POLICIES:
            validate_content_evidence(
                value.get("content_evidence"),
                captured["source_sha256"],
                eligible=value["inspection_complete"] and value["structural_check"] == "passed",
                policy=INSPECTION_POLICIES[captured["source_version"]],
            )
        elif value.get("content_evidence") is not None:
            raise ValueError("Historical reports have no content capture")
    except ValueError:
        raise InspectionError("The content evidence does not match its captured source") from None
    try:
        from librarium.content_evidence import validate_document_text_evidence

        validate_document_text_evidence(value)
    except ValueError:
        raise InspectionError(
            "The document text evidence does not match its captured source"
        ) from None
    try:
        from librarium.source_attribution import validate_source_attribution

        validate_source_attribution(value)
    except ValueError:
        raise InspectionError("The source attribution does not match its captured source") from None
    try:
        validate_identifier_evidence(value)
    except ValueError:
        raise InspectionError(
            "The identifier declarations do not match their captured source"
        ) from None
    if captured["source_version"] in PLANNED_POLICIES:
        from librarium.contents_planning import valid_findings

        plan = value.get("contents_plan")
        if (
            not isinstance(plan, dict)
            or plan.get("policy_version") != plan_policy(captured["source_version"])
            or plan.get("source_sha256") != captured["source_sha256"]
            or plan.get("inspection_policy") != captured["source_version"]
            or plan.get("decision") not in {"keep", "propose", "held"}
            or plan.get("ready") is not False
            or not isinstance(plan.get("reason_codes"), list)
            or not plan["reason_codes"]
            or not all(isinstance(reason, str) for reason in plan["reason_codes"])
            or not isinstance(plan.get("entries"), list)
            or not isinstance(plan.get("existing"), list)
            or not isinstance(plan.get("excluded_targets"), list)
            or not isinstance(plan.get("limitations"), list)
            or (plan["decision"] == "propose" and not plan["entries"])
            or (plan["decision"] != "propose" and bool(plan["entries"]))
            or (plan["decision"] == "keep" and not plan["existing"])
            or plan["policy_version"] == "librarium.contents-plan.v2"
            and not valid_findings(plan)
        ):
            raise InspectionError(
                "The contents plan does not match its preserved source and policy"
            )


def plan_policy(inspection_version):
    from librarium.contents_planning import HISTORICAL_POLICY_VERSION
    from librarium.contents_planning import POLICY_VERSION as PLAN_POLICY

    return PLAN_POLICY if inspection_version == POLICY_VERSION else HISTORICAL_POLICY_VERSION


def _plan_summary(report):
    plan = report["contents_plan"]
    return {
        "policy_version": plan["policy_version"],
        "decision": plan["decision"],
        "reason_codes": deepcopy(plan["reason_codes"]),
    }


def _summary(job_id, captured, bound_fingerprint, report, stored):
    clean = report["structural_check"] == "passed"
    navigation = report["navigation"]
    nav_ok = (
        clean
        and bool(navigation["entries"])
        and not any(f["code"] == "empty_navigation" for f in report["findings"])
    )
    result = {
        "kind": "epub",
        "read_only": True,
        "synthetic": False,
        "input_fingerprint": bound_fingerprint,
        "source_sha256": captured["source_sha256"],
        "source_version": captured["source_version"],
        "policy": captured["policy"],
        "upstream": captured["upstream"],
        "archive_reader": captured["archive_reader"],
        "structural_check": report["structural_check"],
        "inspection_complete": report["inspection_complete"],
        "epubcheck": "not_run",
        "content_acceptance": "not_checked",
        "ready": False,
        "report_sha256": stored["sha256"],
        "report_size": stored["size"],
        "report_url": f"/api/epub-inspections/{job_id}/report",
        "scope": SCOPE,
        "findings": [
            {
                "name": "Source integrity",
                "ok": True,
                "detail": "The preserved source length and SHA-256 match the uploaded bytes.",
            },
            {
                "name": "EPUB structure",
                "ok": clean,
                "detail": "The bounded structural checks passed."
                if clean
                else f"Structural findings need review ({len(report['findings'])} recorded). Open the full report for details.",
            },
            {
                "name": "Navigation",
                "ok": nav_ok,
                "detail": "Navigation was found within the bounded structural check."
                if nav_ok
                else "Navigation could not be confirmed free of structural findings.",
            },
            {"name": "Scope of this check", "ok": False, "detail": SCOPE},
        ],
    }
    if captured["source_version"] in PLANNED_POLICIES:
        result["contents_plan"] = _plan_summary(report)
    return result


@transaction.atomic
def _publish(job_id, token, result, failed=False):
    job = _running(job_id, token).select_for_update().first()
    if job is None:
        return False
    job.state = "failed" if failed else "succeeded"
    job.message = (
        "The preserved EPUB could not be inspected. No library changes were made."
        if failed
        else "Saved the EPUB structural report; readiness was not checked"
    )
    job.result = result
    if not failed:
        job.checkpoint = 4
    job.lease_until = job.lease_token = None
    job.revision += 1
    job.save()
    return True


def advance(job_id, token):
    prepared = _prepare(job_id, token)
    if prepared is None:
        return False
    captured, bound_fingerprint, target = prepared
    result, failed = {}, False
    with _heartbeat(job_id, token) as lost:
        try:
            policy = _validate_input(captured, bound_fingerprint, target)
            data = artifacts.read("source", target, captured["source_size"])
            report_value = inspect_isolated(data, target, policy)
            _validate_report(report_value, captured)
            if not renew(job_id, token) or lost.is_set():
                return False
            stored = artifacts.write_report(report_value)
            result = _summary(job_id, captured, bound_fingerprint, report_value, stored)
        except Exception as error:  # noqa: BLE001
            # Parser/storage exceptions may contain filenames or private host paths.
            from librarium.python_sandbox import EXIT_CODES

            code = getattr(error, "code", None)
            if isinstance(code, str) and code in EXIT_CODES:
                result = {"error_code": code, "ready": False}
            failed = True
    if lost.is_set():
        return False
    return _publish(job_id, token, result, failed)


def report(job):
    if job.kind != "epub":
        raise InspectionError("EPUB inspection not found", 404)
    result = job.result
    if job.state != "succeeded" or not result.get("report_sha256"):
        raise InspectionError("This inspection has no published report")
    captured = job.input
    _validate_input(captured, job.input_fingerprint, job.target_id, historical=True)
    if (
        result.get("source_sha256") != job.target_id
        or result.get("input_fingerprint") != job.input_fingerprint
        or result.get("source_version") != captured["source_version"]
        or result.get("policy") != captured["policy"]
        or result.get("upstream") != captured["upstream"]
        or captured["source_version"] in NATIVE_READER_POLICIES
        and result.get("archive_reader") != captured.get("archive_reader")
    ):
        raise InspectionError("The published report does not match its preserved source")
    artifacts.read("source", job.target_id, captured["source_size"])
    value = artifacts.read_report(result["report_sha256"], result.get("report_size"))
    _validate_report(value, captured)
    if (
        value.get("structural_check") != result.get("structural_check")
        or value.get("inspection_complete") != result.get("inspection_complete")
        or result.get("epubcheck") != "not_run"
        or result.get("content_acceptance") != "not_checked"
        or result.get("ready") is not False
        or captured["source_version"] in PLANNED_POLICIES
        and result.get("contents_plan") != _plan_summary(value)
    ):
        raise InspectionError("The published report does not match its preserved source")
    return {
        "job_id": str(job.pk),
        "source_sha256": job.target_id,
        "report_sha256": result["report_sha256"],
        "report": value,
    }
