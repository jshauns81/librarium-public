"""Durable consent and uncertainty must survive ordinary job lifecycle changes."""

import uuid

import pytest
from django.db import DatabaseError, connection, transaction
from librarium.models import (
    DeliveryApproval,
    DeliveryEvent,
    DeliveryIntent,
    DeliveryReceipt,
    DeliveryState,
    Job,
    UndoIntent,
)


@pytest.mark.django_db
def test_delivery_job_kinds_are_guarded_from_legacy_claimants():
    for kind in ("delivery_prepare", "epub_delivery", "delivery_reconcile", "epub_undo"):
        job = Job.objects.create(
            kind=kind,
            target_id="a" * 64,
            request_key=uuid.uuid4(),
            input={},
            input_fingerprint="b" * 64,
        )
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL librarium.delivery_capability = 'legacy'")
        with pytest.raises(DatabaseError), transaction.atomic():
            Job.objects.filter(pk=job.pk).update(state="running", lease_token=uuid.uuid4())
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL librarium.delivery_capability = 'delivery-v1'")
            Job.objects.filter(pk=job.pk).update(state="running", lease_token=uuid.uuid4())


def test_evidence_models_have_no_path_or_mutable_verdict_fields():
    for model in (DeliveryIntent, DeliveryApproval, DeliveryEvent, DeliveryReceipt, UndoIntent):
        fields = {f.name for f in model._meta.fields}
        assert not fields & {
            "path",
            "library_path",
            "destination",
            "server_url",
            "verdict",
            "state",
        }
        assert {"payload", "sha256", "created_at"} <= fields


def test_uncertain_reservation_is_independent_of_job_state():
    assert "reserved" in {f.name for f in DeliveryState._meta.fields}
    assert DeliveryState._meta.get_field("intent").remote_field.on_delete.__name__ == "PROTECT"


@pytest.mark.django_db
def test_accepted_consent_cannot_be_rewritten_or_deleted():
    from librarium.models import CorrectedEpub

    jobs = [
        Job.objects.create(
            kind="epub_correction",
            target_id=str(i) * 64,
            request_key=uuid.uuid4(),
            input={},
            input_fingerprint="a" * 64,
        )
        for i in (1, 2, 3)
    ]
    output = CorrectedEpub.objects.create(
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
    )
    intent = DeliveryIntent.objects.create(
        job=jobs[0],
        preparation_job=jobs[1],
        output=output,
        source_job=jobs[1],
        validation_job=jobs[2],
        payload={"scope": "epub_only"},
        sha256="a" * 64,
    )
    approval = DeliveryApproval.objects.create(
        intent=intent, payload={"intent_sha256": intent.sha256}, sha256="b" * 64
    )
    for model, instance in [(DeliveryIntent, intent), (DeliveryApproval, approval)]:
        with pytest.raises(DatabaseError), transaction.atomic():
            model.objects.filter(pk=instance.pk).update(payload={})
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"DELETE FROM {model._meta.db_table} WHERE id = %s", [instance.pk])
