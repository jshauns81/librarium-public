"""Bounded navigation over recorded lineage. This projection grants no write authority."""

import uuid

from django.views.decorators.http import require_GET

from librarium import artifacts, file_inspections, retired_jobs
from librarium.models import CorrectedEpub, DeliveryIntent, Job
from librarium.services import fingerprint
from librarium.validation import bounded_text

PINS = ("fv", "fa")
JOB_PINS = {
    "fv": "epub_validation",
    "fa": "book_assessment",
}
# Selections saved before corrected copies and their delivery were retired. A saved
# route that names one resolves to the preserved inspection; an assessment named by
# the retired pins "faj" and "fda" is the nearest kept ancestor and becomes "fa".
RETIRED_PINS = ("fg", "fo", "fov", "faj", "fda", "fdp", "fd", "fdj")
ASSESSMENT_PINS = ("faj", "fda")
PAGE_SIZE = 20


class WorkspaceError(Exception):
    def __init__(self, code="workspace_lineage_changed", status=409):
        self.code, self.status = code, status
        super().__init__(code)


def canonical(value):
    try:
        parsed = uuid.UUID(value)
        if str(parsed) != value:
            raise ValueError
        return str(parsed)
    except TypeError, ValueError, AttributeError:
        raise WorkspaceError("invalid_workspace_selection", 400) from None


def digest(value):
    return isinstance(value, str) and bool(artifacts.DIGEST.fullmatch(value))


def book_number(value):
    return (
        isinstance(value, str)
        and value.isascii()
        and value.isdecimal()
        and 1 <= len(value) <= 20
        and str(int(value)) == value
        and int(value) > 0
    )


def recorded_origin(job):
    """Only the four validated historical locator fields may leave captured inputs."""
    if type(job.input) is not dict:
        raise WorkspaceError()
    if "library_origin" not in job.input:
        return None
    value = job.input["library_origin"]
    if (
        type(value) is not dict
        or set(value) != {"library_uuid", "book_id", "inventory", "format"}
        or (
            value["library_uuid"] is not None
            and (
                not isinstance(value["library_uuid"], str)
                or not value["library_uuid"]
                or not bounded_text(value["library_uuid"], 2000)
            )
        )
        or not book_number(value["book_id"])
        or not digest(value["inventory"])
        or value["format"] != "EPUB"
        or fingerprint(job.input) != job.input_fingerprint
    ):
        raise WorkspaceError()
    return dict(value)


def checked_job(job):
    if type(job.input) is not dict or fingerprint(job.input) != job.input_fingerprint:
        raise WorkspaceError()
    if job.kind == "book_assessment":
        intent = job.input.get("intent")
        if type(intent) is not dict or fingerprint(intent) != job.target_id:
            raise WorkspaceError()
    if job.kind == "book_assessment" and job.state == "succeeded":
        from librarium import library_check_jobs

        try:
            library_check_jobs.assessment_report(job)
        except library_check_jobs.CheckError, TypeError, ValueError, KeyError:
            raise WorkspaceError() from None
    return job


def checked_source(source):
    if source.kind != "epub":
        raise WorkspaceError("workspace_source_not_found", 404)
    try:
        file_inspections._validate_input(
            source.input, source.input_fingerprint, source.target_id, historical=True
        )
    except file_inspections.InspectionError, TypeError, ValueError, KeyError:
        raise WorkspaceError() from None
    if source.state == "succeeded" and (
        not digest(source.result.get("report_sha256"))
        or source.result.get("input_fingerprint") != source.input_fingerprint
        or source.result.get("source_sha256") != source.target_id
        or source.result.get("source_version") != source.input.get("source_version")
        or source.result.get("policy") != source.input.get("policy")
        or source.result.get("upstream") != source.input.get("upstream")
    ):
        raise WorkspaceError()
    recorded_origin(source)
    return source


def source_binding(job, source):
    checked_job(job)
    intent = job.input.get("intent", {})
    source_id = (
        intent.get("source_job_id")
        if job.kind == "book_assessment"
        else job.input.get("source_job_id")
    )
    report = (
        intent.get("report_sha256")
        if job.kind == "book_assessment"
        else job.input.get("source_report_sha256")
    )
    if (
        source.state != "succeeded"
        or source_id != str(source.pk)
        or job.input.get("source_sha256") != source.target_id
        or (job.kind == "book_assessment" and intent.get("source_sha256") != source.target_id)
        or (job.kind == "epub_validation" and job.target_id != source.target_id)
        or report != source.result.get("report_sha256")
        or (
            job.kind == "epub_validation"
            and job.input.get("source_input_fingerprint") != source.input_fingerprint
        )
    ):
        raise WorkspaceError()


def parameters(request, allowed):
    if set(request.GET) - set(allowed) or any(
        len(request.GET.getlist(k)) != 1 for k in request.GET
    ):
        raise WorkspaceError("invalid_workspace_selection", 400)


def get_job(value, kind=None):
    job = Job.objects.filter(pk=canonical(value)).first()
    if job is None:
        raise WorkspaceError("workspace_record_not_found", 404)
    if kind is not None and job.kind != kind:
        raise WorkspaceError()
    return checked_job(job)


def retired_ancestors(job):
    """The preserved inspection and any assessment a retired record was bound to.

    Retired kinds are history: only their captured input integrity and these
    locators are read. Nothing is generated, validated or delivered from them.
    """
    if job.kind in retired_jobs.DELIVERY_KINDS:
        if job.kind == "delivery_prepare":
            output = CorrectedEpub.objects.filter(pk=canonical(job.input.get("subject_id"))).first()
            source = output.source_job_id if output is not None else None
        else:
            delivery = (
                DeliveryIntent.objects.filter(job=job).first()
                if job.kind == "epub_delivery"
                else DeliveryIntent.objects.filter(
                    pk=canonical(job.input.get("subject_id"))
                ).first()
            )
            source = delivery.source_job_id if delivery is not None else None
        if source is None:
            raise WorkspaceError("workspace_record_not_found", 404)
        return str(source), None
    intent = job.input.get("intent")
    intent = intent if type(intent) is dict else {}
    assessment = intent.get("assessment") if job.kind == "epub_correction" else None
    source = job.input.get("source_job_id") or intent.get("source_job_id")
    if not source:
        raise WorkspaceError("workspace_record_not_found", 404)
    return source, assessment


def projection(source, supplied):
    from librarium.views import job_data

    checked_source(source)
    selection: dict[str, str | None] = dict.fromkeys(PINS)
    selection.update(supplied)
    related: dict[str, Job] = {}
    for pin, kind in JOB_PINS.items():
        selected_id = selection[pin]
        if selected_id is None:
            continue
        job = related.get(selected_id) or get_job(selected_id, kind)
        source_binding(job, source)
        related[str(job.pk)] = job
    return {
        "schema_version": "librarium.book-workspace.v1",
        "source": job_data(source),
        "origin": recorded_origin(source),
        "selection": selection,
        "jobs": [job_data(job) for job in related.values()],
    }


def error_response(error):
    from librarium.views import response

    messages = {
        "invalid_workspace_selection": "Use exact recorded workspace selections.",
        "workspace_record_not_found": "The selected workspace record was not found.",
        "workspace_source_not_found": "The preserved EPUB inspection was not found.",
    }
    return response(
        {
            "error": messages.get(
                error.code,
                "These selections do not belong to the same unchanged preserved source. Return to its history and choose the recorded result.",
            ),
            "code": error.code,
        },
        error.status,
    )


@require_GET
def workspace(request, source_id):
    from librarium.views import response

    try:
        parameters(request, PINS + RETIRED_PINS)
        requested = {key: canonical(request.GET[key]) for key in request.GET}
        selected = {key: value for key, value in requested.items() if key in PINS}
        source = get_job(str(source_id), "epub")
        inherited = next((requested[pin] for pin in ASSESSMENT_PINS if pin in requested), None)
        if "fa" not in selected and inherited is not None:
            # An assessment kept from a retired copy selection is still a kept ancestor.
            # When it no longer matches this inspection the book opens at the inspection.
            try:
                return response(projection(source, {**selected, "fa": inherited}))
            except WorkspaceError:
                pass
        return response(projection(source, selected))
    except WorkspaceError as error:
        return error_response(error)
    except TypeError, ValueError, KeyError, AttributeError:
        return error_response(WorkspaceError())


@require_GET
def library_workspaces(request, book_id):
    from librarium.views import job_data, response

    try:
        parameters(request, {"library_uuid", "inventory", "page"})
        library_uuid = request.GET.get("library_uuid", "")
        inventory = request.GET.get("inventory", "")
        page = request.GET.get("page", "1")
        if (
            not book_number(book_id)
            or not library_uuid
            or not bounded_text(library_uuid, 2000)
            or not digest(inventory)
            or not page.isascii()
            or not page.isdecimal()
            or not 1 <= len(page) <= 5
            or str(int(page)) != page
            or not 1 <= int(page) <= 10000
        ):
            raise WorkspaceError("invalid_workspace_selection", 400)
        page = int(page)
        records = Job.objects.filter(
            kind="epub",
            input__library_origin__library_uuid=library_uuid,
            input__library_origin__book_id=book_id,
        )
        count = records.count()
        rows = records.order_by("-created_at", "-id")[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
        values = []
        unavailable_count = 0
        for row in rows:
            try:
                checked_source(row)
                origin = recorded_origin(row)
            except WorkspaceError, TypeError, ValueError, KeyError, AttributeError:
                unavailable_count += 1
                continue
            values.append(
                {
                    "job": job_data(row),
                    "origin": origin,
                    "inventory_matches": origin["inventory"] == inventory,
                }
            )
        return response(
            {
                "sources": values,
                "total": count,
                "page": page,
                "page_size": PAGE_SIZE,
                "unavailable_count": unavailable_count,
            }
        )
    except WorkspaceError as error:
        return error_response(error)
    except TypeError, ValueError, KeyError, AttributeError:
        return error_response(WorkspaceError())


@require_GET
def resolve(request):
    from librarium.views import response

    try:
        parameters(request, {"job"})
        if set(request.GET) != {"job"}:
            raise WorkspaceError("invalid_workspace_selection", 400)
        job = get_job(request.GET["job"])
        pins = {}
        if job.kind in retired_jobs.RETIRED_KINDS:
            source_id, assessment = retired_ancestors(job)
            source = get_job(canonical(source_id), "epub")
            if assessment is not None:
                try:
                    saved = get_job(canonical(assessment), "book_assessment")
                    source_binding(saved, source)
                    pins["fa"] = str(saved.pk)
                except WorkspaceError:
                    pins = {}
            source_id = str(source.pk)
        elif job.kind == "epub":
            source_id = str(job.pk)
        elif job.kind in JOB_PINS.values():
            pins[next(key for key, kind in JOB_PINS.items() if kind == job.kind)] = str(job.pk)
            source_id = (
                job.input.get("intent", {}).get("source_job_id")
                if job.kind == "book_assessment"
                else job.input.get("source_job_id")
            )
        else:
            raise WorkspaceError("workspace_source_not_found", 404)
        source = get_job(canonical(source_id), "epub")
        value = projection(source, pins)
        return response(
            {
                "schema_version": "librarium.book-workspace-resolution.v1",
                "source_job_id": str(source.pk),
                "selection": value["selection"],
            }
        )
    except WorkspaceError as error:
        return error_response(error)
    except TypeError, ValueError, KeyError, AttributeError:
        return error_response(WorkspaceError())
