"""Stored rows of retired corrected-copy and delivery work, built directly from the models.

Librarium no longer runs these job kinds. The rows stay in the database as history, so
tests create them without any application code that produced them.
"""

import uuid

from librarium.delivery_contract import POLICY
from librarium.models import (
    CorrectedEpub,
    DeliveryApproval,
    DeliveryIntent,
    DeliveryState,
    DeliveryTargetBinding,
    Job,
)
from librarium.services import fingerprint

TARGET = {"library_uuid": str(uuid.UUID(int=1)), "book_id": "1", "book_uuid": str(uuid.UUID(int=2))}
META = {"fields_sha256": "1" * 64, "cover_sha256": None, "other_formats": {}}


def observation(sha, inventory="9" * 64):
    return {"sha256": sha, "size": 10, "metadata": dict(META), "inventory": inventory}


def record(model, payload, **fields):
    return model.objects.create(payload=payload, sha256=fingerprint(payload), **fields)


def make_job(kind, subject, value=None, attempts=0, **fields):
    intent = {**(value or {}), "subject_id": str(subject)}
    captured = {
        "intent": intent,
        "subject_id": str(subject),
        "policy": POLICY,
        "title": "synthetic",
        "source_version": POLICY,
    }
    return Job.objects.create(
        kind=kind,
        target_id=fingerprint(intent),
        request_key=uuid.uuid4(),
        input=captured,
        input_fingerprint=fingerprint(captured),
        attempts=attempts,
        **fields,
    )


def make_output(source=None):
    """A stored corrected copy; `source` is the inspection job it was made from, if any."""
    jobs = [
        Job.objects.create(
            kind="epub_correction",
            target_id=uuid.uuid4().hex * 2,
            request_key=uuid.uuid4(),
            input={},
            input_fingerprint="a" * 64,
        )
        for _ in (1, 2, 3)
    ]
    if source is not None:
        jobs[1] = source
    return CorrectedEpub.objects.create(
        generation_job=jobs[0],
        source_job=jobs[1],
        initial_validation_job=jobs[2],
        source_sha256="a" * 64,
        source_report_sha256="b" * 64,
        output_sha256="c" * 64,
        output_size=10,
        capture_sha256="d" * 64,
        capture_size=10,
        generation_report_sha256="e" * 64,
        generation_report_size=10,
    ), jobs


def make_delivery(output, jobs, *, reserved=True):
    job = make_job("epub_delivery", output.pk, {"synthetic": str(uuid.uuid4())})
    request = {
        "operation_id": str(uuid.uuid4()),
        "mode": "delivery",
        "target": TARGET,
        "before": observation("a" * 64),
        "output": {"sha256": "c" * 64, "size": 10},
    }
    payload = {
        "intent": job.input["intent"],
        "grant": {
            "payload": {
                "request": request,
                "original": {"kind": "source", "sha256": "a" * 64, "size": 10},
            },
            "signature": "0" * 64,
        },
        "review_expires_at": "2999-01-01T00:00:00+00:00",
    }
    saved = record(
        DeliveryIntent,
        payload,
        job=job,
        preparation_job=jobs[0],
        output=output,
        source_job=jobs[1],
        validation_job=jobs[2],
    )
    record(DeliveryApproval, {"intent_sha256": saved.sha256}, intent=saved)
    record(DeliveryTargetBinding, TARGET, intent=saved)
    key = fingerprint({k: TARGET[k] for k in ("library_uuid", "book_id")})
    DeliveryState.objects.create(intent=saved, target_key=key, reserved=reserved)
    return job, saved, request
