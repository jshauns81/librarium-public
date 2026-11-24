"""Bounded historical report reads; current claims require both source fences."""

import math

from django.views.decorators.http import require_GET

from librarium import catalogue, direct_library, library_reconciliation
from librarium.models import LibraryReconciliation
from librarium.views import response

PAGE_SIZE = 24


def parameters(request, allowed):
    if set(request.GET) - allowed or any(len(request.GET.getlist(k)) != 1 for k in request.GET):
        raise ValueError
    page = int(request.GET.get("page", "1"))
    if not 1 <= page <= 10000:
        raise ValueError
    return page


def summary(saved):
    report = saved.report
    return {
        "request_key": str(saved.pk),
        "created_at": saved.created_at.isoformat(),
        "catalogue": report["catalogue"],
        "inventory": report["inventory"],
        "counts": report["counts"],
        "total": report["total"],
        "observation": "historical",
        "file_identity": report["file_identity"],
        "duplicates": report["duplicates"],
        "ready": False,
    }


def selected_coverage(key, pin):
    try:
        saved = library_reconciliation.read(key)
    except library_reconciliation.ReconciliationError as error:
        raise ValueError from error
    result = summary(saved)
    result["status"] = "historical"
    if result["catalogue"] == pin:
        try:
            with direct_library.snapshot(result["inventory"]["token"]) as (_, _, current):
                if current["library_uuid"] == result["inventory"]["library_uuid"]:
                    result["status"] = "matches_selected_sources"
        except direct_library.DirectLibraryError as error:
            result["status"] = (
                "historical" if error.code == "direct_library_changed" else "unconfirmed"
            )
    result["message"] = (
        "Saved metadata coverage under the selected catalogue pin; file identity and duplicates are unassessed."
    )
    return result


@require_GET
def index(request):
    try:
        page = parameters(request, {"page", "version", "sha256"})
        reports = LibraryReconciliation.objects.order_by("-created_at", "request_key")
        if "version" in request.GET or "sha256" in request.GET:
            # A selected catalogue filters by both stored pins together, never one alone.
            version, sha256 = request.GET.get("version", ""), request.GET.get("sha256", "")
            if not catalogue.valid_version(version) or not catalogue.DIGEST.fullmatch(sha256):
                raise ValueError
            reports = reports.filter(catalogue_version=version, catalogue_sha256=sha256)
        total = reports.count()
        # Project summaries in SQL so discovery never loads the per-book JSON arrays.
        reports = reports.values(
            "request_key",
            "created_at",
            *[
                f"report__{key}"
                for key in (
                    "catalogue",
                    "inventory",
                    "counts",
                    "total",
                    "file_identity",
                    "duplicates",
                )
            ],
        )[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
        rows = []
        for row in reports:
            rows.append(
                {
                    "request_key": str(row["request_key"]),
                    "created_at": row["created_at"].isoformat(),
                    **{
                        key.removeprefix("report__"): value
                        for key, value in row.items()
                        if key.startswith("report__")
                    },
                    "observation": "historical",
                    "ready": False,
                }
            )
        return response(
            {
                "reports": rows,
                "page": page,
                "page_size": PAGE_SIZE,
                "total": total,
                "pages": max(1, math.ceil(total / PAGE_SIZE)),
            }
        )
    except ValueError:
        return response({"error": "Choose a valid saved coverage page"}, 400)


@require_GET
def detail(request, request_key):
    try:
        page = parameters(request, {"page", "status"})
        status = request.GET.get("status")
        if status is not None and status not in library_reconciliation.STATUSES:
            raise ValueError
        saved = LibraryReconciliation.objects.get(pk=request_key)
        entries = saved.report["books"]
        if status is not None:
            entries = [entry for entry in entries if entry["status"] == status]
        total = len(entries)
        return response(
            {
                **summary(saved),
                "inventory_total": saved.report["total"],
                "previous": saved.report["previous"],
                "changes": saved.report["changes"],
                "status": status,
                "page": page,
                "page_size": PAGE_SIZE,
                "pages": max(1, math.ceil(total / PAGE_SIZE)),
                "total": total,
                "books": entries[(page - 1) * PAGE_SIZE : page * PAGE_SIZE],
                "scope": saved.report["scope"],
            }
        )
    except ValueError:
        return response({"error": "Choose a valid saved coverage status and page"}, 400)
    except LibraryReconciliation.DoesNotExist:
        return response({"error": "Saved coverage not found"}, 404)
