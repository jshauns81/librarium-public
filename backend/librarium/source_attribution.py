"""Bounded printed title/credit observations, independent of package declarations."""

import re

POLICY = "librarium.epub-source-attribution.v1"
INSPECTION_POLICY = "librarium.epub-structure.v7"
MAX_OBSERVATIONS = 8
MAX_CREDITS = 16
MAX_LABEL = 256
MAX_FRONT_DOCUMENTS = 4
SCOPE = (
    "Short title and credit source labels from linear documents among the first four spine entries, before "
    "unclassified body text or a narrative boundary. Semantic titlepage candidates and "
    "unclassified heading leads are distinct. Markup and inline hiding are observed; CSS "
    "rendering, complete narrative, edition and whole-file identity are not authenticated."
)
XHTML = "{http://www.w3.org/1999/xhtml}"
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"
EPUB_PREFIX = "{http://www.idpf.org/2007/ops}prefix"
HISTORICAL = {f"librarium.epub-structure.v{n}" for n in range(1, 7)}
TITLE_MARKERS = {"title", "fulltitle", "doc-title"}
CREDIT_MARKERS = {"author", "docauthor", "doc-author", "z3998:author"}
EXCLUDED_TYPES = {
    "toc",
    "landmarks",
    "page-list",
    "preview",
    "advertisement",
    "other-credits",
    "acknowledgments",
    "bibliography",
    "index",
    "bio",
    "colophon",
    "copyright-page",
    "credits",
    "endnotes",
    "footnote",
    "glossary",
    "pagelist",
}
NARRATIVE_TYPES = {"bodymatter", "chapter", "subchapter", "part", "prologue", "epilogue"}
SKIPPED_TAGS = {
    XHTML + name
    for name in (
        "head",
        "script",
        "style",
        "nav",
        "aside",
        "template",
        "noscript",
        "iframe",
        "object",
    )
}
NARRATIVE_HEADING = re.compile(r"^(chapter|part|prologue|epilogue|introduction)\b", re.IGNORECASE)
DIGEST = re.compile(r"[a-f0-9]{64}")


class _CaptureRefused(Exception):
    pass


def unconfirmed(source_sha256, reason):
    return {
        "policy": POLICY,
        "status": "unconfirmed",
        "source_sha256": source_sha256,
        "observations": [],
        "reason": reason,
        "scope": SCOPE,
    }


def _types(element):
    semantics = set(element.get(EPUB_TYPE, "").split())
    for role in element.get("role", "").split():
        if role.startswith("doc-") and role[4:] in EXCLUDED_TYPES | NARRATIVE_TYPES:
            semantics.add(role[4:])
    return semantics


def _excluded(element):
    style = re.sub(r"\s+", "", element.get("style", "")).casefold()
    return (
        element.tag in SKIPPED_TAGS
        or "hidden" in element.attrib
        or element.get("aria-hidden", "").casefold() == "true"
        or re.search(r"(?:^|;)(?:display:none|visibility:hidden)(?:!important)?(?:;|$)", style)
        is not None
        or bool(_types(element) & EXCLUDED_TYPES)
    )


def _label(element, positions, marker, budget):
    if any(_excluded(child) or _types(child) & NARRATIVE_TYPES for child in element.iter()):
        return None
    text = " ".join("".join(element.itertext()).split())
    if len(text) > min(MAX_LABEL, budget.policy.max_metadata_chars):
        raise _CaptureRefused("label_limit")
    if not text:
        return None
    if not _text(text, min(MAX_LABEL, budget.policy.max_metadata_chars)):
        raise _CaptureRefused("unsupported_label_text")
    return budget.record({"text": text, "source_index": positions[element], "marker": marker})


def _marked_labels(element, positions, budget, inherited_prefix):
    titles: list[dict] = []
    credits: list[dict] = []
    stack = [(element, inherited_prefix)]
    while stack:
        current, prefix = stack.pop()
        prefix = current.get(EPUB_PREFIX, prefix)
        if _excluded(current):
            continue
        if current is not element and _types(current) & (NARRATIVE_TYPES | {"titlepage"}):
            raise _CaptureRefused("contained_scope")
        markers = _types(current) | set(current.get("role", "").split())
        title_marker = sorted(markers & TITLE_MARKERS)
        credit_marker = sorted(markers & CREDIT_MARKERS)
        if "z3998:author" in credit_marker and not re.search(
            r"(?:^|\s)z3998:\s+http://www\.daisy\.org/z3998/2012/vocab/structure/#(?:\s|$)", prefix
        ):
            credit_marker.remove("z3998:author")
        if title_marker or credit_marker:
            label = _label(current, positions, (title_marker or credit_marker)[0], budget)
            if label is not None:
                (titles if title_marker else credits).append(label)
                if len(credits) > MAX_CREDITS or len(titles) > 1:
                    raise _CaptureRefused("label_count_limit")
            continue
        stack.extend((child, prefix) for child in reversed(current))
    return (titles[0] if titles else None), credits


def capture(report, trees, budget):
    source = report["source_sha256"]
    observations: list[dict] = []
    stopped = False
    try:
        paths = [entry["path"] for entry in report["spine"]]
        if len(set(paths)) != len(paths):
            return unconfirmed(source, "ambiguous_spine")
        documents = {entry["path"]: entry for entry in report["documents"]}
        for spine_index, entry in enumerate(report["spine"][:MAX_FRONT_DOCUMENTS]):
            if stopped:
                break
            path = entry["path"]
            if entry["linear"] != "yes" or path in report["navigation"]["nav_paths"]:
                continue
            root = trees.get(path)
            if root is None or root.tag != XHTML + "html":
                return unconfirmed(source, "unsupported_front_resource")
            if _excluded(root) or _types(root) & NARRATIVE_TYPES:
                return unconfirmed(source, "excluded_front_scope")
            bodies = root.findall(XHTML + "body")
            if len(bodies) != 1:
                return unconfirmed(source, "ambiguous_front_body")
            positions = {element: index for index, element in enumerate(root.iter())}
            stack = [(bodies[0], root.get(EPUB_PREFIX, ""), False)]
            while stack:
                element, prefix, exiting = stack.pop()
                if exiting:
                    if element.tail and element.tail.strip():
                        stopped = True
                        break
                    continue
                prefix = element.get(EPUB_PREFIX, prefix)
                if _excluded(element):
                    if element.tail and element.tail.strip():
                        stopped = True
                        break
                    continue
                stack.append((element, prefix, True))
                semantics = _types(element)
                if semantics & NARRATIVE_TYPES:
                    stopped = True
                    break
                candidate = None
                if "titlepage" in semantics:
                    title, credits = _marked_labels(element, positions, budget, prefix)
                    if title is not None or credits:
                        candidate = ("semantic_titlepage", "container_candidate", title, credits)
                    else:
                        stopped = True
                elif element.tag in {XHTML + "h1", XHTML + "h2"}:
                    text = " ".join("".join(element.itertext()).split())
                    if NARRATIVE_HEADING.match(text):
                        stopped = True
                        break
                    title = _label(element, positions, "heading", budget)
                    if title is not None:
                        candidate = ("front_matter_lead", "unclassified", title, [])
                    stopped = True
                elif element.text and element.text.strip():
                    stopped = True
                    break
                if candidate is not None:
                    rule, scope, title, credits = candidate
                    observations.append(
                        budget.record(
                            {
                                "id": f"source-title-{len(observations) + 1}",
                                "spine_index": spine_index,
                                "path": path,
                                "resource_sha256": documents[path]["byte_sha256"],
                                "source_index": positions[element],
                                "rule": rule,
                                "scope": scope,
                                "title": title,
                                "credits": credits,
                            }
                        )
                    )
                    if len(observations) > MAX_OBSERVATIONS:
                        raise _CaptureRefused("observation_limit")
                elif "titlepage" not in semantics:
                    stack.extend((child, prefix, False) for child in reversed(element))
                if stopped:
                    break
        if not observations:
            return unconfirmed(source, "no_title_credit_observations")
        return {
            "policy": POLICY,
            "status": "recorded",
            "source_sha256": source,
            "observations": observations,
            "reason": None,
            "scope": SCOPE,
        }
    except _CaptureRefused as error:
        return unconfirmed(source, str(error))


def _text(value, maximum):
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    )


def _index(value, maximum):
    return type(value) is int and 0 <= value < maximum


def validate_source_attribution(report):
    """Validate the captured shape and source locators without interpreting identity."""
    try:
        version = report["policy"]["version"]
        value = report.get("source_attribution")
        if version in HISTORICAL:
            if value is not None:
                raise ValueError
            return None
        if version not in {
            INSPECTION_POLICY,
            "librarium.epub-structure.v8",
            "librarium.epub-structure.v9",
            "librarium.epub-structure.v10",
            "librarium.epub-structure.v11",
        } or not isinstance(value, dict):
            raise ValueError
        if (
            set(value) != set(unconfirmed(None, "unknown"))
            or value["policy"] != POLICY
            or value["source_sha256"] != report["source_sha256"]
            or value["scope"] != SCOPE
            or not isinstance(value["observations"], list)
        ):
            raise ValueError
        observations = value["observations"]
        if value["status"] == "unconfirmed":
            if (
                observations
                or not isinstance(value["reason"], str)
                or not re.fullmatch(r"[a-z_]{1,80}", value["reason"])
            ):
                raise ValueError
            return value
        if (
            value["status"] != "recorded"
            or value["reason"] is not None
            or not report["inspection_complete"]
            or report["structural_check"] != "passed"
            or not 1 <= len(observations) <= MAX_OBSERVATIONS
        ):
            raise ValueError
        documents = {entry["path"]: entry for entry in report["documents"]}
        previous = (-1, -1)
        for number, item in enumerate(observations, 1):
            if not isinstance(item, dict) or set(item) != {
                "id",
                "spine_index",
                "path",
                "resource_sha256",
                "source_index",
                "rule",
                "scope",
                "title",
                "credits",
            }:
                raise ValueError
            if not _index(item["spine_index"], min(MAX_FRONT_DOCUMENTS, len(report["spine"]))):
                raise ValueError
            spine = report["spine"][item["spine_index"]]
            document = documents[item["path"]]
            count = document["source_element_count"]
            if (
                item["id"] != f"source-title-{number}"
                or spine["path"] != item["path"]
                or spine["linear"] != "yes"
                or item["path"] in report["navigation"]["nav_paths"]
                or not isinstance(item["resource_sha256"], str)
                or not DIGEST.fullmatch(item["resource_sha256"])
                or item["resource_sha256"] != document["byte_sha256"]
                or not _index(count, report["policy"]["limits"]["max_xml_nodes"] + 1)
                or not _index(item["source_index"], count)
                or (item["spine_index"], item["source_index"]) <= previous
                or (item["rule"], item["scope"])
                not in {
                    ("semantic_titlepage", "container_candidate"),
                    ("front_matter_lead", "unclassified"),
                }
                or not isinstance(item["credits"], list)
                or len(item["credits"]) > MAX_CREDITS
                or (item["title"] is None and not item["credits"])
            ):
                raise ValueError
            previous = (item["spine_index"], item["source_index"])
            labels = ([item["title"]] if item["title"] is not None else []) + item["credits"]
            seen = set()
            for label in labels:
                markers = (
                    (TITLE_MARKERS | {"heading"}) if label is item["title"] else CREDIT_MARKERS
                )
                if (
                    not isinstance(label, dict)
                    or set(label) != {"text", "source_index", "marker"}
                    or not _text(
                        label["text"],
                        min(MAX_LABEL, report["policy"]["limits"]["max_metadata_chars"]),
                    )
                    or label["marker"] not in markers
                    or not _index(label["source_index"], count)
                    or label["source_index"] < item["source_index"]
                    or label["source_index"] in seen
                ):
                    raise ValueError
                seen.add(label["source_index"])
            if item["rule"] == "front_matter_lead" and (
                item["credits"]
                or item["title"] is None
                or item["title"]["marker"] != "heading"
                or item["title"]["source_index"] != item["source_index"]
            ):
                raise ValueError
            if item["rule"] == "semantic_titlepage" and (
                item["title"] is not None and item["title"]["marker"] == "heading"
            ):
                raise ValueError
        return value
    except KeyError, TypeError, IndexError, AttributeError, ValueError:
        raise ValueError("Invalid source attribution capture or binding") from None
