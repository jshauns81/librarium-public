"""Explicit pinned checks with durable intent and lease-fenced publication."""

import json
import uuid
from copy import deepcopy
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models.functions import Now

from librarium import catalogue, content_trust, file_inspections, library_reconciliation
from librarium.models import Job, LibraryReconciliation
from librarium.services import fingerprint
from librarium.validation import bounded_text

KINDS = {"library_reconcile", "book_assessment"}
POLICY = "librarium.library-check-jobs.v1"
MAX_RESULT_BYTES = 2 * 1024 * 1024
FAILURE_MESSAGES = {
    "library_changed": "The library inventory changed. Reconcile current sources before retrying.",
    "coverage_mismatch": "Saved coverage does not match these sources. Reconcile before retrying.",
    "reader_busy": "The library reader was busy. Retry this check.",
    "library_file_unavailable": "A library file was unavailable. Check its connection before retrying.",
    "library_unavailable": "The library could not be read. Check its connection before retrying.",
    "catalogue_unavailable": "The selected catalogue could not be read. Check its connection and pin.",
    "policy_unavailable": "The captured check policy is unavailable. Request a new check.",
}


class CheckError(Exception):
    def __init__(self, message, status=409, code="check_unavailable"):
        super().__init__(message)
        self.status = status
        self.code = code


def failure_code(error):
    codes = {
        "policy_unavailable": "policy_unavailable",
        "coverage_mismatch": "coverage_mismatch",
        "library_changed": "library_changed",
        "direct_library_changed": "library_changed",
        "direct_library_busy": "reader_busy",
        "direct_library_missing": "library_file_unavailable",
        "direct_library_unavailable": "library_unavailable",
        "catalogue_unavailable": "catalogue_unavailable",
    }
    code = getattr(error, "code", None)
    return (
        codes.get(code, "library_check_unavailable")
        if isinstance(code, str)
        else "library_check_unavailable"
    )


def request_uuid(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 45:
        raise CheckError("Choose an explicit UUID request key", 400)
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise CheckError("Choose an explicit UUID request key", 400) from error


def validate_request(kind, value):
    required = (
        {"version", "sha256", "inventory"}
        if kind == "library_reconcile"
        else {
            "version",
            "sha256",
            "catalogue_work_id",
            "source_sha256",
            "report_sha256",
            "reconciliation",
        }
    )
    allowed = required | (
        {"previous"} if kind == "library_reconcile" else {"comparison_inspections", "reference"}
    )
    if not isinstance(value, dict) or not required <= value.keys() <= allowed:
        raise CheckError("Choose the exact pinned check inputs", 400)
    if (
        not isinstance(value["version"], str)
        or not catalogue.valid_version(value["version"])
        or not isinstance(value["sha256"], str)
        or not catalogue.DIGEST.fullmatch(value["sha256"])
    ):
        raise CheckError("Choose an explicit catalogue version and digest", 400)
    if kind == "library_reconcile":
        inventory = value["inventory"]
        if (
            not isinstance(inventory, dict)
            or set(inventory) != {"token", "library_uuid"}
            or not isinstance(inventory["token"], str)
            or not catalogue.DIGEST.fullmatch(inventory["token"])
            or not isinstance(inventory["library_uuid"], str)
            or not inventory["library_uuid"]
            or not bounded_text(inventory["library_uuid"], 2000)
        ):
            raise CheckError("Choose one recorded library inventory and library UUID", 400)
        if "previous" in value:
            request_uuid(value["previous"])
    else:
        request_uuid(value["reconciliation"])
        from librarium.duplicate_evidence import validate_pins

        validate_pins(value.get("comparison_inspections", []), error_type=CheckError)
        if "reference" in value:
            try:
                content_trust.validate_pin(value["reference"])
            except content_trust.TrustError as error:
                raise CheckError(str(error), 400) from None
        if (
            not isinstance(value["catalogue_work_id"], str)
            or not value["catalogue_work_id"]
            or not bounded_text(value["catalogue_work_id"], 80)
            or any(
                not isinstance(value[field], str) or not catalogue.DIGEST.fullmatch(value[field])
                for field in ("source_sha256", "report_sha256")
            )
        ):
            raise CheckError("Choose one work and its preserved source/report digests", 400)


def replay(key, kind, intent):
    existing = Job.objects.filter(request_key=key).first()
    if existing is None:
        return None
    if existing.kind == kind and existing.input.get("intent") == intent:
        return existing
    raise CheckError("This request key belongs to different check inputs")


def enqueue(kind, value, key_text, *, source_id=None):
    if kind not in KINDS:
        raise CheckError("Choose a supported library check", 400)
    validate_request(kind, value)
    key = request_uuid(key_text)
    intent = deepcopy(value)
    for field in ("previous", "reconciliation"):
        if field in intent:
            intent[field] = str(request_uuid(intent[field]))
    if kind == "book_assessment":
        intent["source_job_id"] = str(source_id)
        if "comparison_inspections" in intent:
            for entry in intent["comparison_inspections"]:
                entry["job_id"] = str(request_uuid(entry["job_id"]))
    existing = replay(key, kind, intent)
    if existing is not None:
        return existing
    if kind == "book_assessment":
        source = Job.objects.filter(pk=source_id, kind="epub", state="succeeded").first()
        if source is None:
            raise CheckError("A completed EPUB inspection is required", 404)
        if (
            source.target_id != value["source_sha256"]
            or source.result.get("report_sha256") != value["report_sha256"]
        ):
            raise CheckError("The selected inspection source or report changed")
        if not LibraryReconciliation.objects.filter(pk=value["reconciliation"]).exists():
            raise CheckError("The selected saved reconciliation does not exist", 404)
    elif LibraryReconciliation.objects.filter(pk=key).exists():
        raise CheckError("This request key already names a saved reconciliation")
    if intent.get("previous") == str(key):
        raise CheckError("Choose a distinct previous reconciliation", 400)
    if kind == "book_assessment":
        from librarium.book_assessment import POLICY as engine_policy
    else:
        engine_policy = library_reconciliation.POLICY
    captured = {
        "kind": kind,
        "policy": POLICY,
        "engine_policy": engine_policy,
        "intent": intent,
        "title": "Library reconciliation"
        if kind == "library_reconcile"
        else "Book identity and duplicates",
        "source_version": value["version"],
        "source_sha256": value.get("source_sha256", value["sha256"]),
    }
    if kind == "book_assessment":
        # Enqueue captures only the explicit pin; trust configuration is read by the worker.
        captured["authentication_policy"] = content_trust.POLICY
    try:
        with transaction.atomic():
            existing = replay(key, kind, intent)
            if existing is not None:
                return existing
            return Job.objects.create(
                kind=kind,
                target_id=fingerprint(intent),
                request_key=key,
                input=captured,
                input_fingerprint=fingerprint(captured),
            )
    except IntegrityError:
        existing = replay(key, kind, intent)
        if existing is not None:
            return existing
        raise CheckError("This check already has an active request; recover its progress") from None


def recover(kind, key, source_id=None):
    job = Job.objects.filter(kind=kind, request_key=key).first()
    if (
        job is not None
        and source_id is not None
        and job.input["intent"].get("source_job_id") != str(source_id)
    ):
        raise CheckError("This request key belongs to another inspection")
    return job


def running(job_id, token):
    return Job.objects.filter(
        pk=job_id, kind__in=KINDS, state="running", lease_token=token, lease_until__gt=Now()
    )


def renew(job_id, token):
    return bool(running(job_id, token).update(lease_until=Now() + timedelta(seconds=10)))


@transaction.atomic
def prepare(job_id, token):
    job = running(job_id, token).select_for_update().first()
    if job is None:
        return None
    job.checkpoint = 1
    job.revision += 1
    job.save()
    return job


@transaction.atomic
def publish(job_id, token, result, report=None, *, failed=False):
    job = running(job_id, token).select_for_update().first()
    if job is None:
        return False
    if report is not None:
        # The job and its complete coverage commit together under the live lease lock.
        LibraryReconciliation.objects.create(
            request_key=job.request_key,
            catalogue_version=report["catalogue"]["version"],
            catalogue_sha256=report["catalogue"]["sha256"],
            previous_key=request_uuid(report["previous"]) if report["previous"] else None,
            report=report,
        )
    result = {
        **result,
        "input_fingerprint": job.input_fingerprint,
        "ready": False,
        "read_only": True,
    }
    result["result_fingerprint"] = fingerprint(result)
    job.result = result
    job.state = "failed" if failed else "succeeded"
    job.message = (
        FAILURE_MESSAGES.get(
            result.get("error_code"),
            "The selected check could not complete; preserved evidence is unchanged",
        )
        if failed
        else "Saved the selected check"
    )
    job.checkpoint = 1 if failed else 4
    job.lease_token = job.lease_until = None
    job.revision += 1
    job.save()
    return True


def advance(job_id, token):
    job = prepare(job_id, token)
    if job is None:
        return False
    report = None
    with file_inspections._heartbeat(job_id, token, renew_lease=renew) as lost:
        try:
            captured = job.input
            if (
                captured.get("kind") != job.kind
                or captured.get("policy") != POLICY
                or fingerprint(captured) != job.input_fingerprint
            ):
                raise CheckError(
                    "The captured check policy is unavailable", code="policy_unavailable"
                )
            intent = captured["intent"]
            request = {key: value for key, value in intent.items() if key != "source_job_id"}
            validate_request(job.kind, request)
            if fingerprint(intent) != job.target_id:
                raise CheckError("The captured check inputs changed")
            if job.kind == "library_reconcile":
                if captured.get("engine_policy") != library_reconciliation.POLICY:
                    raise CheckError(
                        "The captured reconciliation policy is unavailable",
                        code="policy_unavailable",
                    )
                report = library_reconciliation.build_report(
                    job.request_key,
                    intent["version"],
                    intent["sha256"],
                    previous=intent.get("previous"),
                    expected_inventory=intent["inventory"],
                    cancel_check=lost.is_set,
                )
                result = {
                    "reconciliation": str(job.request_key),
                    **{key: report[key] for key in ("catalogue", "inventory", "counts", "total")},
                    "observation": "historical",
                    "policy_version": report["policy_version"],
                }
            else:
                from librarium import book_assessment

                if (
                    captured.get("engine_policy") != book_assessment.POLICY
                    or captured.get("authentication_policy") != content_trust.POLICY
                ):
                    raise CheckError(
                        "The captured book assessment policy is unavailable",
                        code="policy_unavailable",
                    )
                source = Job.objects.get(pk=intent["source_job_id"])
                if (
                    source.target_id != intent["source_sha256"]
                    or source.result.get("report_sha256") != intent["report_sha256"]
                ):
                    raise CheckError("The selected preserved source changed")
                result = book_assessment.assess(
                    source,
                    intent["version"],
                    intent["sha256"],
                    intent["catalogue_work_id"],
                    reconciliation=library_reconciliation.read(intent["reconciliation"]),
                    cancel_check=lost.is_set,
                    comparison_inspections=intent.get("comparison_inspections", []),
                    reference=intent.get("reference"),
                )
            if len(json.dumps(result).encode()) > MAX_RESULT_BYTES:
                raise CheckError("The selected check exceeds its saved result limit")
        except Exception as error:  # noqa: BLE001 -- Keep library paths and raw parser failures private.
            result = {"error_code": failure_code(error)}
            report = None
            failed = True
        else:
            failed = False
        if lost.is_set() or not renew(job_id, token):
            return False
    if lost.is_set():
        return False
    try:
        return publish(job_id, token, result, report, failed=failed)
    except IntegrityError:
        return publish(job_id, token, {"error_code": "reconciliation_key_conflict"}, failed=True)


def assessment_report(job):
    result = deepcopy(job.result)
    digest = result.pop("result_fingerprint", None)
    if (
        job.kind != "book_assessment"
        or job.state != "succeeded"
        or fingerprint(job.input) != job.input_fingerprint
        or job.input.get("policy") != POLICY
        or fingerprint(job.input.get("intent")) != job.target_id
        or result.get("input_fingerprint") != job.input_fingerprint
        or result.get("policy_version") != job.input.get("engine_policy")
        or digest != fingerprint(result)
    ):
        raise CheckError("A completed bound book assessment is required")
    intent = job.input["intent"]
    if (
        result.get("job_id") != intent.get("source_job_id")
        or result.get("source_sha256") != intent.get("source_sha256")
        or result.get("report_sha256") != intent.get("report_sha256")
        or result.get("reconciliation_key") != intent.get("reconciliation")
        or result.get("catalogue", {}).get("version") != intent.get("version")
        or result.get("catalogue", {}).get("sha256") != intent.get("sha256")
        or result.get("file_work_identity", {}).get("work_id") != intent.get("catalogue_work_id")
        or result.get("ready") is not False
        or result.get("correction_admission") != "held"
    ):
        raise CheckError("The assessment does not match its preserved sources")
    from librarium import book_assessment

    if result["policy_version"] == book_assessment.POLICY:
        auth = result.get("reference_authentication")
        pin = intent.get("reference")
        expected = {
            "schema_version": content_trust.POLICY,
            "source_sha256": intent.get("source_sha256"),
            "report_sha256": intent.get("report_sha256"),
            "catalogue": {
                "version": intent.get("version"),
                "sha256": intent.get("sha256"),
                "work_id": intent.get("catalogue_work_id"),
            },
            **(
                {"status": "not_requested", "reference_id": None, "registry_sha256": None}
                if pin is None
                else pin
            ),
        }
        if not isinstance(auth, dict) or any(auth.get(k) != v for k, v in expected.items()):
            raise CheckError("The reference authentication does not match its preserved pins")
    return result


HISTORY_PAGE_SIZE = 24
HISTORY_SUMMARY = {
    "library_reconcile": {
        "policy_version": "result__policy_version",
        "error_code": "result__error_code",
        "reconciliation": "result__reconciliation",
    },
    "book_assessment": {
        "policy_version": "result__policy_version",
        "assessed_at": "result__assessed_at",
        "error_code": "result__error_code",
        "reference_authentication": "result__reference_authentication__status",
        "exact_bytes": "result__duplicates__exact_bytes__status",
    },
}


def history(kind, page, source_id=None):
    """One bounded page of captured checks; summaries are projected without loading results."""
    from django.db.models.fields.json import KT

    records = Job.objects.filter(kind=kind)
    if source_id is not None:
        records = records.filter(input__intent__source_job_id=str(source_id))
    total = records.count()
    fields = HISTORY_SUMMARY[kind]
    rows = (
        records.defer("result")
        .annotate(**{f"summary_{name}": KT(path) for name, path in fields.items()})
        .order_by("-created_at", "-id")[(page - 1) * HISTORY_PAGE_SIZE : page * HISTORY_PAGE_SIZE]
    )
    return rows, total, fields
