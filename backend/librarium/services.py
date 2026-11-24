import hashlib
import json
import logging
import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.functions import Now

from librarium import catalogue_reviews, retired_jobs
from librarium.catalogue import DIGEST, CatalogueError, valid_version
from librarium.models import Job, Work
from librarium.validation import bounded_text

logger = logging.getLogger(__name__)
STAGES = [
    "Bound the saved source versions",
    "Compared catalogue and library titles",
    "Validated the supplied ISBN",
    "Saved the metadata comparison",
]


def fingerprint(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@transaction.atomic
def enqueue(work_id: str, request_key: str) -> Job:
    key = uuid.UUID(request_key)
    # Lock the work before looking for a live job: separate browser intents serialize here.
    work = Work.objects.select_for_update().get(pk=work_id)
    existing = Job.objects.filter(request_key=key).first()
    if existing:
        if existing.work_id != work_id:
            raise ValueError("This request key belongs to a different work")
        return existing
    if Job.objects.filter(work=work, state__in=["queued", "running"]).exists():
        raise ValueError("This work already has an active inspection; refresh its progress")
    payload = dict(work.payload)
    fixture_failure = (
        payload.pop("fault", None) == "once"
        and not Job.objects.filter(work=work, state="failed").exists()
    )
    result = Job.objects.create(
        work=work,
        target_id=work.pk,
        request_key=key,
        input=payload,
        input_fingerprint=fingerprint(payload),
        fixture_failure=fixture_failure,
    )
    logger.info("job_enqueued id=%s work=%s", result.pk, work.pk)
    return result


REVIEW_FIELDS = {"catalogue_work_id", "version", "sha256"}


def review_request(payload) -> tuple[str, str, str]:
    if (
        not isinstance(payload, dict)
        or set(payload) != REVIEW_FIELDS
        or not all(isinstance(payload[field], str) for field in REVIEW_FIELDS)
        or not payload["catalogue_work_id"]
        or not bounded_text(payload["catalogue_work_id"], 80)
        or not valid_version(payload["version"])
        or not DIGEST.fullmatch(payload["sha256"])
    ):
        raise CatalogueError(
            "Choose one catalogue work with its snapshot version and fingerprint", 400
        )
    return payload["catalogue_work_id"], payload["version"], payload["sha256"]


def replay(key: uuid.UUID, request: tuple[str, str, str]) -> Job | None:
    """Return the job this key already created, or refuse a key reused for another request."""
    existing = Job.objects.filter(request_key=key).first()
    if existing is None:
        return None
    if (
        existing.kind == "catalogue"
        and (
            existing.target_id,
            existing.input["source_version"],
            existing.input["source_sha256"],
        )
        == request
    ):
        return existing
    raise CatalogueError("This request key belongs to a different request", 409)


def enqueue_catalogue(payload, request_key: str) -> Job:
    """Queue a read-only review of one pinned catalogue work, idempotently by request key.

    Raises CatalogueError with an HTTP status: 400 invalid request, 404 unknown work,
    409 key reuse, active review or changed/unavailable snapshot, 422 oversized metadata.
    """
    request = review_request(payload)
    try:
        key = uuid.UUID(request_key)
    except (TypeError, ValueError, AttributeError) as error:
        raise CatalogueError("Use a valid request key", 400) from error
    # An exact replay must not depend on the snapshot still being mounted.
    existing = replay(key, request)
    if existing:
        return existing
    captured = catalogue_reviews.capture_catalogue(*request)
    try:
        with transaction.atomic():
            existing = replay(key, request)
            if existing:
                return existing
            if Job.objects.filter(
                kind="catalogue", target_id=request[0], state__in=["queued", "running"]
            ).exists():
                # A concurrent replay of this key may have committed since the check above.
                existing = replay(key, request)
                if existing:
                    return existing
                raise CatalogueError(
                    "This catalogue work already has an active review; refresh its progress", 409
                )
            job = Job.objects.create(
                kind="catalogue",
                target_id=request[0],
                work=None,
                request_key=key,
                input=captured,
                input_fingerprint=fingerprint(captured),
            )
    except IntegrityError:
        # A concurrent request won the key or the active slot; report what it created.
        existing = replay(key, request)
        if existing:
            return existing
        raise CatalogueError(
            "This catalogue work already has an active review; refresh its progress", 409
        ) from None
    logger.info("job_enqueued id=%s kind=catalogue target=%s", job.pk, job.target_id)
    return job


@transaction.atomic
def cancel(job_id: uuid.UUID) -> Job:
    job = Job.objects.select_for_update().get(pk=job_id)
    if job.state in {"queued", "running"}:
        job.state = "cancelled"
        job.message = (
            retired_jobs.CANCELLED_MESSAGE
            if job.kind in retired_jobs.RETIRED_KINDS
            else "Cancelled; no library changes were made"
        )
        job.lease_token = None
        job.lease_until = None
        job.revision += 1
        job.save()
        logger.info("job_cancelled id=%s revision=%s", job.pk, job.revision)
    return job


@transaction.atomic
def claim() -> Job | None:
    # Retired kinds are never listed here, so no worker claims or advances them.
    while True:
        job = (
            Job.objects.select_for_update(skip_locked=True)
            .filter(
                kind__in=[
                    "synthetic",
                    "catalogue",
                    "epub",
                    "epub_validation",
                    "library_reconcile",
                    "book_assessment",
                ]
            )
            .filter(Q(state="queued") | Q(state="running", lease_until__lte=Now()))
            .order_by("created_at")
            .first()
        )
        if job is None:
            return None
        if job.attempts < 3:
            break
        job.state = "failed"
        job.message = "Worker recovery limit reached; request a new inspection"
        job.lease_token = None
        job.lease_until = None
        job.revision += 1
        job.save()
    job.state = "running"
    job.attempts += 1
    job.lease_token = uuid.uuid4()
    job.lease_until = Now() + timedelta(seconds=10)
    if job.checkpoint:
        job.message = "Resuming from saved progress"
    elif job.kind == "catalogue":
        job.message = "Reviewing catalogue metadata"
    elif job.kind == "epub":
        job.message = "Inspecting the preserved EPUB"
    elif job.kind == "epub_validation":
        job.message = "Validating the preserved EPUB with EPUBCheck"
    elif job.kind == "library_reconcile":
        job.message = "Reconciling the selected library inventory"
    elif job.kind == "book_assessment":
        job.message = "Assessing book identity and duplicates"
    else:
        job.message = "Comparing saved metadata"
    job.revision += 1
    job.save()
    job.refresh_from_db()
    logger.info("job_claimed id=%s attempt=%s checkpoint=%s", job.pk, job.attempts, job.checkpoint)
    return job


def valid_isbn(value: str) -> bool:
    return (
        len(value) == 13
        and value.isascii()
        and value.isdigit()
        and sum(int(char) * (1 if index % 2 == 0 else 3) for index, char in enumerate(value)) % 10
        == 0
    )


def title_finding(payload: dict) -> dict:
    title_matches = (
        payload["title"].strip().casefold() == payload["library_title"].strip().casefold()
    )
    return {
        "name": "Title comparison",
        "ok": title_matches,
        "detail": f"Library and catalogue titles agree: {payload['title']}"
        if title_matches
        else f"Library title {payload['library_title']} differs from catalogue title {payload['title']}",
    }


def isbn_finding(payload: dict) -> dict:
    isbn_valid = valid_isbn(payload["library_isbn"])
    return {
        "name": "ISBN checksum",
        "ok": isbn_valid,
        "detail": f"Library ISBN {payload['library_isbn']} has a valid ISBN-13 checksum"
        if isbn_valid
        else f"Library ISBN {payload['library_isbn']} fails its checksum",
    }


def bound_result(payload: dict, bound_fingerprint: str) -> dict:
    return {
        "read_only": True,
        "synthetic": True,
        "input_fingerprint": bound_fingerprint,
        "source_version": payload["source_version"],
        "file_sha256": payload["file_sha256"],
        "findings": [],
        "scope": "Metadata only. Book content and structural validity were not checked.",
    }


def advance(job_id: uuid.UUID, token: uuid.UUID) -> bool:
    if Job.objects.filter(pk=job_id, kind__in=["library_reconcile", "book_assessment"]).exists():
        from librarium.library_check_jobs import advance as advance_library_check

        return advance_library_check(job_id, token)
    if Job.objects.filter(pk=job_id, kind="epub_validation").exists():
        from librarium.epub_validations import advance as advance_validation

        return advance_validation(job_id, token)
    if Job.objects.filter(pk=job_id, kind="epub").exists():
        from librarium.file_inspections import advance as advance_epub

        return advance_epub(job_id, token)
    return _advance_metadata(job_id, token)


@transaction.atomic
def _advance_metadata(job_id: uuid.UUID, token: uuid.UUID) -> bool:
    job = (
        Job.objects.select_for_update()
        .filter(
            pk=job_id,
            kind__in=["synthetic", "catalogue"],
            state="running",
            lease_token=token,
            lease_until__gt=Now(),
        )
        .first()
    )
    if job is None:
        return False
    if job.kind == "catalogue":
        job.checkpoint += 1
        job.result = catalogue_reviews.advance_result(
            job.checkpoint, job.input, job.result, job.input_fingerprint
        )
        job.message = catalogue_reviews.STAGES[job.checkpoint - 1]
        if job.checkpoint == len(catalogue_reviews.STAGES):
            job.state = "succeeded"
    elif job.fixture_failure:
        job.state = "failed"
        job.message = (
            "Synthetic source unavailable (intentional fixture fault). Retry to compare again."
        )
    else:
        job.checkpoint += 1
        if job.checkpoint == 1:
            job.result = bound_result(job.input, job.input_fingerprint)
        elif job.checkpoint == 2:
            job.result["findings"].append(title_finding(job.input))
        elif job.checkpoint == 3:
            job.result["findings"].append(isbn_finding(job.input))
        job.message = STAGES[job.checkpoint - 1]
        if job.checkpoint == 4:
            job.state = "succeeded"
    job.revision += 1
    job.lease_until = Now() + timedelta(seconds=10)
    if job.state != "running":
        job.lease_token = None
        job.lease_until = None
    job.save()
    logger.info(
        "job_progress id=%s revision=%s state=%s checkpoint=%s",
        job.pk,
        job.revision,
        job.state,
        job.checkpoint,
    )
    return True
