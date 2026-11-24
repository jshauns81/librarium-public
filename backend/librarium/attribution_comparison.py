"""Pinned bibliographic corroboration of bounded source title/credit observations."""

from librarium import catalogue, file_inspections, package_comparison

POLICY = "librarium.source-attribution-comparison.v1"
SCOPE = (
    "Source title/credit labels compared with one selected pinned bibliographic catalogue work. "
    "Labels describe XML source, not rendered visibility. Catalogue title, authors and ISBN "
    "share one bibliographic lineage; agreement does not authenticate the complete narrative, "
    "edition, collection coverage or semantic equivalence. No library change is authorized."
)


def compare(envelope, db, info, work_id):
    from librarium.source_attribution import validate_source_attribution

    report = envelope["report"]
    source = envelope["source_sha256"]
    report_sha256 = envelope["report_sha256"]
    if (
        not isinstance(source, str)
        or not catalogue.DIGEST.fullmatch(source)
        or not isinstance(report_sha256, str)
        or not catalogue.DIGEST.fullmatch(report_sha256)
        or report.get("expected_sha256") != source
        or report.get("source_sha256") not in (None, source)
    ):
        raise file_inspections.InspectionError("The source attribution pins do not match")
    try:
        capture = validate_source_attribution(report)
    except ValueError:
        raise file_inspections.InspectionError(
            "Source attribution capture is unavailable"
        ) from None
    work = package_comparison.selected_work(db, work_id)
    candidates = (
        [
            item
            for item in capture["observations"]
            if item["rule"] == "semantic_titlepage" and item["scope"] == "container_candidate"
        ]
        if capture is not None and capture["status"] == "recorded"
        else []
    )
    status = "unconfirmed"
    title = None
    creators = None
    reason = "no_container_observation"
    if capture is None:
        reason = "not_captured"
    elif capture["status"] != "recorded":
        reason = capture["reason"]
    elif len(candidates) > 1:
        status = "ambiguous"
        reason = "multiple_container_observations"
    elif (
        len(candidates) == 1
        and report["inspection_complete"]
        and report["structural_check"] == "passed"
    ):
        candidate = candidates[0]
        title_text = candidate["title"]["text"] if candidate["title"] is not None else None
        names = [credit["text"] for credit in candidate["credits"]]
        title_state = "unknown"
        if title_text and package_comparison.normalized(work["title"]):
            title_state = (
                "same"
                if package_comparison.normalized(title_text)
                == package_comparison.normalized(work["title"])
                else "different"
            )
        title = {"status": title_state, "epub": title_text, "catalogue": work["title"]}
        creators = package_comparison.creator_finding(
            names, work["authors"], package_comparison.name_owners(db, names), True
        )
        if creators["status"] == "ambiguous":
            status, reason = "ambiguous", "ambiguous_credits"
        elif title_state == "different" or creators["status"] == "different":
            status, reason = "conflicting", "source_catalogue_conflict"
        elif title_state == creators["status"] == "same":
            status, reason = "corroborated", "complete_title_and_credits"
        else:
            reason = "incomplete_title_or_credits"
    return {
        "schema_version": POLICY,
        "policy_version": POLICY,
        "job_id": envelope["job_id"],
        "source_sha256": source,
        "report_sha256": report_sha256,
        "catalogue": {**info, **work},
        "observation_policy": capture["policy"] if capture is not None else None,
        "capture": capture["status"] if capture is not None else "not_captured",
        "status": status,
        "reason": reason,
        "observation_ids": [item["id"] for item in candidates],
        "title": title,
        "creators": creators,
        "whole_file_identity": "unconfirmed",
        "content_authentication": "unconfirmed",
        "ready": False,
        "scope": SCOPE,
    }
