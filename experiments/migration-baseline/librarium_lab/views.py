from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_safe

from .identity import to_isbn13, work_key
from .snapshots import SnapshotError, load_lock


class SecurityHeaders:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Cache-Control"] = "no-store"
        response["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'none'; style-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        response["Referrer-Policy"] = "same-origin"
        return response


def baseline_data():
    if not (settings.LAB_ROOT / "snapshots.lock.json").is_file():
        raise SnapshotError("Baseline not captured")
    lock = load_lock(settings.LAB_ROOT)
    return {**lock, "scope": "experiment", "migration_ready": False,
            "gates": {"source_capture": "implemented", "helper_parity": "run separately",
                      "workflow_parity": "not assessed", "frontend_choice": "open",
                      "production_migration": "not authorized"}}


@require_safe
def home(request):
    try:
        data = baseline_data()
    except SnapshotError:
        data = {"sources": {}, "error": "Capture source baselines before assessing migration."}
    return render(request, "librarium_lab/home.html", data)


@require_safe
def health(request):
    return JsonResponse({"ok": True, "scope": "experiment"})


@require_safe
def baseline(request):
    try:
        return JsonResponse(baseline_data())
    except SnapshotError:
        return JsonResponse({"error": "baseline_unavailable"}, status=503)


@require_safe
def identity_probe(request):
    values = {key: request.GET.get(key, "") for key in ("title", "authors", "isbn")}
    if any(len(value) > 1000 for value in values.values()):
        return JsonResponse({"error": "input_too_long"}, status=400)
    return JsonResponse({"work_key": work_key(values["title"], values["authors"]),
                         "isbn13": to_isbn13(values["isbn"]), "scope": "experiment"})
