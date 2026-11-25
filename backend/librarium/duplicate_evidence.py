"""Explicit preserved-file comparisons; text equality never clears semantic duplicates."""

import uuid
from collections import defaultdict, deque
from itertools import pairwise
from typing import Any

from django.conf import settings

from librarium import catalogue, file_inspections, package_comparison
from librarium.content_evidence import (
    INSPECTION_POLICIES,
    validate_content_evidence,
    validate_document_text_evidence,
)
from librarium.models import Job

MAX_COMPARISONS = 8
MAX_RESOURCE_MATCHES = 64
MAX_DOCUMENT_TEXT_MATCHES = 64
DOCUMENT_TEXT_SCOPE = "ordered_xhtml_spine_document_body_source_text"
DOCUMENT_TEXT_LIMITATIONS = (
    "Exact normalized document body source text only, including hidden and script/style text. "
    "Shared boilerplate can produce a lead. Case and punctuation remain significant. "
    "Document text containment does not establish story or whole-book containment, semantic "
    "equivalence, independent content authentication, media identity or duplicate clearance. "
    "Different text and changed document boundaries do not exclude overlap. Each selected "
    "document pairs with the first unused comparison occurrence of its digest and character count; "
    "pairing_order_preserved describes that pairing, not all possible subsequence alignments. "
    "Text-empty documents, such as image-only pages, are not compared or counted."
)
RESOURCE_SCOPE = "ordered_xhtml_spine_resource_bytes"
RESOURCE_LIMITATIONS = (
    "Exact shared spine XML bytes only. Shared boilerplate can produce a lead. Resource "
    "containment does not establish story or whole-book containment, semantic equivalence, "
    "independent content authentication, or duplicate clearance. Different resource bytes do "
    "not exclude overlapping text. Each selected resource pairs with the first unused comparison occurrence of its digest; "
    "pairing_order_preserved "
    "describes that pairing, not all possible subsequence alignments."
)


def validate_pins(values, *, error_type):
    if not isinstance(values, (list, tuple)) or len(values) > MAX_COMPARISONS:
        raise error_type("Choose at most eight explicit comparison inspections", 400)
    seen = set()
    for value in values:
        if (
            not isinstance(value, dict)
            or set(value) != {"job_id", "source_sha256", "report_sha256"}
            or not isinstance(value["job_id"], str)
            or len(value["job_id"]) > 45
            or any(
                not isinstance(value[key], str) or not catalogue.DIGEST.fullmatch(value[key])
                for key in ("source_sha256", "report_sha256")
            )
        ):
            raise error_type("Choose exact comparison inspection and digest pins", 400)
        try:
            key = str(uuid.UUID(value["job_id"]))
        except ValueError:
            raise error_type("Choose an explicit comparison inspection UUID", 400) from None
        if key in seen:
            raise error_type("Choose each comparison inspection once", 400)
        seen.add(key)


def _content(report):
    if report.get("policy", {}).get("version") not in {
        "librarium.epub-structure.v6",
        "librarium.epub-structure.v7",
        "librarium.epub-structure.v8",
        "librarium.epub-structure.v9",
        "librarium.epub-structure.v10",
        "librarium.epub-structure.v11",
    }:
        return None
    value = report.get("content_evidence")
    if not isinstance(value, dict) or value.get("status") != "recorded":
        return None
    return value


def _spine_resources(report):
    if (
        report.get("policy", {}).get("version")
        not in {
            "librarium.epub-structure.v6",
            "librarium.epub-structure.v7",
            "librarium.epub-structure.v8",
            "librarium.epub-structure.v9",
            "librarium.epub-structure.v10",
            "librarium.epub-structure.v11",
        }
        or report.get("inspection_complete") is not True
        or report.get("structural_check") != "passed"
    ):
        raise ValueError("Resource evidence requires a complete eligible capture")
    content = report["content_evidence"]
    validate_content_evidence(
        content,
        report["source_sha256"],
        policy=INSPECTION_POLICIES[report["policy"]["version"]],
    )
    if content["status"] != "recorded":
        raise ValueError("Resource evidence requires recorded content")
    limits = report["policy"]["limits"]
    for name, ceiling in (("max_members", 2048), ("max_records", 8192), ("max_name_chars", 512)):
        if type(limits[name]) is not int or not 1 <= limits[name] <= ceiling:
            raise ValueError("Invalid captured resource limit")

    def path(value):
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= limits["max_name_chars"]
            or "\\" in value
            or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value)
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("Invalid captured resource path")
        return value

    spine, documents, manifest = (report[name] for name in ("spine", "documents", "manifest"))
    if (
        any(not isinstance(values, list) for values in (spine, documents, manifest))
        or any(len(values) > limits["max_members"] for values in (spine, documents, manifest))
        or len(spine) + len(documents) + len(manifest) > limits["max_records"]
        or not spine
        or content["spine_documents"] != len(spine)
    ):
        raise ValueError("Invalid captured resource counts")
    digests = {}
    for document in documents:
        location = path(document["path"])
        digest = document["byte_sha256"]
        if (
            location in digests
            or not isinstance(digest, str)
            or not catalogue.DIGEST.fullmatch(digest)
        ):
            raise ValueError("Invalid captured resource digest")
        digests[location] = digest
    media = {}
    for item in manifest:
        location = path(item["path"])
        if location in media:
            raise ValueError("Ambiguous captured resource")
        media[location] = item["media_type"]
    values = []
    seen = set()
    for index, item in enumerate(spine):
        location = path(item["path"])
        if (
            type(item["index"]) is not int
            or item["index"] != index
            or location in seen
            or media.get(location) not in {"application/xhtml+xml", "text/html"}
            or location not in digests
        ):
            raise ValueError("Invalid captured spine resource")
        seen.add(location)
        values.append({"path": location, "spine_index": index, "sha256": digests[location]})
    return values


def resource_overlap(selected_report, comparison_report):
    result: dict[str, Any] = {
        "scope": RESOURCE_SCOPE,
        "status": "unconfirmed",
        "relation": "unconfirmed",
        "selected_documents": None,
        "comparison_documents": None,
        "matched_documents": None,
        "pairing_order_preserved": None,
        "matches": [],
        "truncated": False,
        "limitations": RESOURCE_LIMITATIONS,
    }
    try:
        selected = _spine_resources(selected_report)
        comparison = _spine_resources(comparison_report)
    except KeyError, TypeError, ValueError, AttributeError:
        return result
    by_digest: defaultdict[str, deque[dict]] = defaultdict(deque)
    for entry in comparison:
        by_digest[entry["sha256"]].append(entry)
    matches: list[dict] = []
    indexes = []
    for entry in selected:
        candidates = by_digest[entry["sha256"]]
        if candidates:
            other = candidates.popleft()
            indexes.append(other["spine_index"])
            if len(matches) < MAX_RESOURCE_MATCHES:
                matches.append(
                    {
                        "sha256": entry["sha256"],
                        "selected": {key: entry[key] for key in ("path", "spine_index")},
                        "comparison": {key: other[key] for key in ("path", "spine_index")},
                    }
                )
    count = len(indexes)
    relation = "shared_spine_resources"
    if count == len(selected) == len(comparison):
        relation = "all_spine_resources_same"
    elif count == len(selected):
        relation = "selected_spine_resources_contained"
    elif count == len(comparison):
        relation = "comparison_spine_resources_contained"
    elif not count:
        relation = "no_shared_spine_resources"
    result.update(
        status="recorded",
        relation=relation,
        selected_documents=len(selected),
        comparison_documents=len(comparison),
        matched_documents=count,
        pairing_order_preserved=all(left < right for left, right in pairwise(indexes))
        if count
        else None,
        matches=matches,
        truncated=count > len(matches),
    )
    return result


def document_text_overlap(selected_report, comparison_report):
    result: dict[str, Any] = {
        "scope": DOCUMENT_TEXT_SCOPE,
        "status": "unconfirmed",
        "relation": "unconfirmed",
        "selected_documents": None,
        "comparison_documents": None,
        "matched_documents": None,
        "pairing_order_preserved": None,
        "matches": [],
        "truncated": False,
        "limitations": DOCUMENT_TEXT_LIMITATIONS,
    }
    try:
        for report in (selected_report, comparison_report):
            validate_document_text_evidence(report)
            if report["document_text_evidence"]["status"] != "recorded":
                return result
        # Text-empty pages (images, blanks) share no text with anything.
        selected = [
            row
            for row in selected_report["document_text_evidence"]["documents"]
            if row["text_chars"]
        ]
        comparison = [
            row
            for row in comparison_report["document_text_evidence"]["documents"]
            if row["text_chars"]
        ]
    except KeyError, TypeError, ValueError, AttributeError:
        return result
    by_digest: defaultdict[tuple[str, int], deque[dict]] = defaultdict(deque)
    for entry in comparison:
        by_digest[(entry["text_sha256"], entry["text_chars"])].append(entry)
    matches: list[dict] = []
    indexes = []
    for entry in selected:
        candidates = by_digest[(entry["text_sha256"], entry["text_chars"])]
        if candidates:
            other = candidates.popleft()
            indexes.append(other["spine_index"])
            if len(matches) < MAX_DOCUMENT_TEXT_MATCHES:
                matches.append(
                    {
                        "text_sha256": entry["text_sha256"],
                        "text_chars": entry["text_chars"],
                        "selected": {
                            key: entry[key] for key in ("path", "spine_index", "resource_sha256")
                        },
                        "comparison": {
                            key: other[key] for key in ("path", "spine_index", "resource_sha256")
                        },
                    }
                )
    count = len(indexes)
    relation = "shared_document_text"
    if count == len(selected) == len(comparison):
        relation = "all_document_text_same"
    elif count == len(selected):
        relation = "selected_document_text_contained"
    elif count == len(comparison):
        relation = "comparison_document_text_contained"
    elif not count:
        relation = "no_shared_document_text"
    result.update(
        status="recorded",
        relation=relation,
        selected_documents=len(selected),
        comparison_documents=len(comparison),
        matched_documents=count,
        pairing_order_preserved=all(left < right for left, right in pairwise(indexes))
        if count
        else None,
        matches=matches,
        truncated=count > len(matches),
    )
    return result


def compare_inspections(source, envelope, pins, pin, work_id, entries, origin, budget):
    from librarium.book_assessment import (
        MAX_TOTAL_BYTES,
        AssessmentError,
        _BudgetExceeded,
        identity,
    )

    validate_pins(pins, error_type=AssessmentError)
    selected = _content(envelope["report"])
    comparisons = []
    with catalogue.snapshot(
        settings.LIBRARIUM_CATALOGUE_DIR,
        pin["version"],
        pin["sha256"],
        settings.LIBRARIUM_CATALOGUE_FIXTURE,
    ) as (db, _):
        for requested in pins:
            budget.check()
            candidate = Job.objects.filter(
                pk=requested["job_id"], kind="epub", state="succeeded"
            ).first()
            if (
                candidate is None
                or candidate.pk == source.pk
                or candidate.target_id != requested["source_sha256"]
                or candidate.result.get("report_sha256") != requested["report_sha256"]
            ):
                raise AssessmentError("The selected comparison inspection does not match its pins")
            budget.consumed += candidate.input["source_size"]
            if budget.consumed > MAX_TOTAL_BYTES:
                raise _BudgetExceeded
            try:
                other = file_inspections.report(candidate)
            except (file_inspections.InspectionError, ValueError) as error:
                raise AssessmentError("The selected comparison report is unavailable") from error
            content = _content(other["report"])
            text_relation = "unconfirmed"
            if (
                selected is not None
                and content is not None
                and selected["policy"] == content["policy"]
            ):
                text_relation = (
                    "same" if selected["text_sha256"] == content["text_sha256"] else "different"
                )
            native = candidate.input.get("library_origin")
            membership = "not_applicable" if native is None else "unconfirmed"
            book_id = None
            if (
                isinstance(native, dict)
                and native.get("library_uuid") == origin["library_uuid"]
                and native.get("inventory") == origin["inventory"]
                and native.get("format") == "EPUB"
                and native.get("book_id") in entries
            ):
                book_id = native["book_id"]
                membership = "recorded"
            work, edition = identity(package_comparison.compare(other, db, pin, work_id))
            comparisons.append(
                {
                    "inspection": dict(requested),
                    "inspection_policy": other["report"]["policy"]["version"],
                    "content_policy": content["policy"] if content else None,
                    "text_relation": text_relation,
                    "resource_overlap": resource_overlap(envelope["report"], other["report"]),
                    "document_text_overlap": document_text_overlap(
                        envelope["report"], other["report"]
                    ),
                    "exact_bytes": other["source_sha256"] == envelope["source_sha256"],
                    "inventory_membership": membership,
                    "book_id": book_id,
                    "relationship": "same_native_origin"
                    if membership == "recorded" and book_id == origin["book_id"]
                    else "candidate",
                    "library_origin": native,
                    "declared_work": {"status": work["status"], "work_id": work["work_id"]},
                    "declared_edition": edition,
                    "observation": "historical",
                }
            )
    return {
        "scope": "explicit_preserved_inspections",
        "clearance": "unconfirmed",
        "comparisons": comparisons,
        "possible_count": sum(
            (
                row["text_relation"] == "same"
                or (row["resource_overlap"]["matched_documents"] or 0) > 0
                or (row["document_text_overlap"]["matched_documents"] or 0) > 0
            )
            and row["relationship"] != "same_native_origin"
            for row in comparisons
        ),
        "limitations": "Selected historical reports only. Equal normalized source text, document text or shared spine XML bytes supply possible duplicate leads, including shared boilerplate; different text or resource bytes cannot exclude semantic duplicates. Resource or document text containment is not whole-book containment. Media, language, edition and content authentication remain unconfirmed. No current library file content is inferred from a saved report.",
    }
