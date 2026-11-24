"""Versioned source-text comparison evidence; never rendered or narrative identity."""

import hashlib
import re

HISTORICAL_POLICY = "librarium.epub-content-evidence.v1"
POLICY = "librarium.epub-content-evidence.v2"
SCOPE = (
    "Ordered XHTML spine body source text, including non-linear, hidden and script/style text. "
    "Unicode whitespace and block/document boundaries normalize to spaces; case and punctuation "
    "remain. Resource hashes cover ordered spine XML bytes, not linked assets. Text equality "
    "does not prove media, language, edition, narrative completeness or semantic equivalence."
)
# v2 records text-empty spine documents (image-only or blank pages) instead of refusing the
# whole capture. They contribute no text, stay in the resource hash and are counted in
# ``empty_spine_documents``; the scope text is unchanged so the bounded envelope still fits.
# Inspection v10 captures v2; v6-v9 reports keep their original v1 evidence.
INSPECTION_POLICIES = {
    "librarium.epub-structure.v6": HISTORICAL_POLICY,
    "librarium.epub-structure.v7": HISTORICAL_POLICY,
    "librarium.epub-structure.v8": HISTORICAL_POLICY,
    "librarium.epub-structure.v9": HISTORICAL_POLICY,
    "librarium.epub-structure.v10": POLICY,
}
DOCUMENT_TEXT_INSPECTIONS = frozenset(
    {"librarium.epub-structure.v8", "librarium.epub-structure.v9", "librarium.epub-structure.v10"}
)


def unconfirmed(source_sha256, reason, policy=POLICY):
    value = {
        "policy": policy,
        "status": "unconfirmed",
        "source_sha256": source_sha256,
        "text_sha256": None,
        "spine_bytes_sha256": None,
        "text_chars": None,
        "spine_documents": None,
        "reason": reason,
        "scope": SCOPE,
    }
    if policy == POLICY:
        value["empty_spine_documents"] = None
    return value


class _TextDigest:
    def __init__(self):
        self.digest = hashlib.sha256()
        self.chars = 0
        self.pending_space = False

    def add(self, text):
        if not text:
            return
        value = " ".join(text.split())
        if not value:
            self.pending_space = bool(self.chars)
            return
        if self.pending_space or self.chars and text[0].isspace():
            self.digest.update(b" ")
            self.chars += 1
        self.digest.update(value.encode("utf-8"))
        self.chars += len(value)
        self.pending_space = text[-1].isspace()


def _body_pieces(body, boundaries):
    stack = [(body, False)]
    while stack:
        element, exiting = stack.pop()
        if exiting:
            if element.tag in boundaries:
                yield " "
            if element is not body:
                yield element.tail
        else:
            if element.tag in boundaries:
                yield " "
            yield element.text
            stack.append((element, True))
            stack.extend((child, False) for child in reversed(element))


def capture(report, trees, archive, boundaries, xhtml):
    """Consume already bounded parsed trees in the isolated inspection child."""
    source = report["source_sha256"]
    spine = report["spine"]
    manifest = report["manifest"]
    paths = [item["path"] for item in spine]
    if not paths or len(set(paths)) != len(paths):
        return unconfirmed(source, "ambiguous_spine")
    text = _TextDigest()
    resources = hashlib.sha256()
    empty = 0
    for path in paths:
        entries = [item for item in manifest if item["path"] == path]
        tree = trees.get(path)
        if (
            len(entries) != 1
            or entries[0]["media_type"] not in {"application/xhtml+xml", "text/html"}
            or tree is None
            or tree.tag != xhtml + "html"
        ):
            return unconfirmed(source, "unsupported_spine_resource")
        bodies = tree.findall(xhtml + "body")
        if len(bodies) != 1:
            return unconfirmed(source, "ambiguous_body")
        previous_chars = text.chars
        text.add(" ")
        for piece in _body_pieces(bodies[0], boundaries):
            text.add(piece)
            if text.chars > report["policy"]["limits"]["max_xml_text_chars"]:
                return unconfirmed(source, "content_text_limit")
        empty += text.chars == previous_chars
        raw = archive.read(path)
        resources.update(len(raw).to_bytes(8, "big"))
        resources.update(raw)
    if not text.chars:
        return unconfirmed(source, "empty_spine_body")
    return {
        "policy": POLICY,
        "status": "recorded",
        "source_sha256": source,
        "text_sha256": text.digest.hexdigest(),
        "spine_bytes_sha256": resources.hexdigest(),
        "text_chars": text.chars,
        "spine_documents": len(paths),
        "empty_spine_documents": empty,
        "reason": None,
        "scope": SCOPE,
    }


def validate_content_evidence(value, source_sha256, *, eligible=True, policy=POLICY):
    """Validate a captured observation under its inspection's own content policy."""
    shape = unconfirmed(source_sha256, "unconfirmed", policy)
    if (
        policy not in {POLICY, HISTORICAL_POLICY}
        or not isinstance(value, dict)
        or set(value) != set(shape)
        or value["policy"] != policy
        or value["source_sha256"] != source_sha256
        or value["scope"] != shape["scope"]
    ):
        raise ValueError("Invalid content evidence binding")
    if policy == POLICY:
        empty = value["empty_spine_documents"]
        if value["status"] == "recorded" and (
            type(empty) is not int
            or type(value["spine_documents"]) is not int
            or not 0 <= empty < value["spine_documents"]
        ):
            raise ValueError("Invalid empty document count")
        if value["status"] == "unconfirmed" and empty is not None:
            raise ValueError("Invalid unconfirmed content evidence")
    if value["status"] == "unconfirmed":
        if (
            not isinstance(value["reason"], str)
            or not re.fullmatch(r"[a-z_]{1,80}", value["reason"])
            or any(
                value[key] is not None
                for key in (
                    "text_sha256",
                    "spine_bytes_sha256",
                    "text_chars",
                    "spine_documents",
                )
            )
        ):
            raise ValueError("Invalid unconfirmed content evidence")
    elif value["status"] == "recorded":
        if (
            not eligible
            or value["reason"] is not None
            or any(
                not isinstance(value[key], str) or not re.fullmatch(r"[a-f0-9]{64}", value[key])
                for key in ("text_sha256", "spine_bytes_sha256")
            )
            or type(value["text_chars"]) is not int
            or not 1 <= value["text_chars"] <= 16 * 1024 * 1024
            or type(value["spine_documents"]) is not int
            or not 1 <= value["spine_documents"] <= 2048
        ):
            raise ValueError("Invalid recorded content evidence")
    else:
        raise ValueError("Invalid content evidence status")


HISTORICAL_DOCUMENT_TEXT_POLICY = "librarium.epub-document-text.v1"
HISTORICAL_DOCUMENT_TEXT_SCOPE = (
    "Spine body source text with content-evidence v1 normalization; XML/position bound. "
    "No authentication."
)
DOCUMENT_TEXT_POLICY = "librarium.epub-document-text.v2"
DOCUMENT_TEXT_SCOPE = HISTORICAL_DOCUMENT_TEXT_SCOPE  # zero-character rows are text-empty
EMPTY_TEXT_SHA256 = hashlib.sha256(b"").hexdigest()


def unconfirmed_document_text(source_sha256, reason):
    return {
        "policy": DOCUMENT_TEXT_POLICY,
        "status": "unconfirmed",
        "source_sha256": source_sha256,
        "documents": [],
        "reason": reason,
        "scope": DOCUMENT_TEXT_SCOPE,
    }


def capture_document_text(report, trees, boundaries, xhtml, record):
    source = report["source_sha256"]
    content = report["content_evidence"]
    if content["status"] != "recorded":
        return unconfirmed_document_text(source, content["reason"])
    resources = {document["path"]: document["byte_sha256"] for document in report["documents"]}
    documents = []
    for index, entry in enumerate(report["spine"]):
        path = entry["path"]
        text = _TextDigest()
        body = trees[path].find(xhtml + "body")
        for piece in _body_pieces(body, boundaries):
            text.add(piece)
            if text.chars > report["policy"]["limits"]["max_xml_text_chars"]:
                return unconfirmed_document_text(source, "content_text_limit")
        documents.append(
            record(
                {
                    "path": path,
                    "spine_index": index,
                    "resource_sha256": resources[path],
                    "text_sha256": text.digest.hexdigest(),
                    "text_chars": text.chars,
                }
            )
        )
    return {
        "policy": DOCUMENT_TEXT_POLICY,
        "status": "recorded",
        "source_sha256": source,
        "documents": documents,
        "reason": None,
        "scope": DOCUMENT_TEXT_SCOPE,
    }


def _document_text_shape(version, source):
    value = unconfirmed_document_text(source, "unconfirmed")
    if INSPECTION_POLICIES[version] == HISTORICAL_POLICY:
        value.update(policy=HISTORICAL_DOCUMENT_TEXT_POLICY, scope=HISTORICAL_DOCUMENT_TEXT_SCOPE)
    return value


def _validate_document_text_evidence(report):
    value = report.get("document_text_evidence")
    version = report["policy"]["version"]
    if version not in DOCUMENT_TEXT_INSPECTIONS:
        if value is not None:
            raise ValueError("Historical inspections have no document text capture")
        return
    current = INSPECTION_POLICIES[version] == POLICY
    source = report["source_sha256"]
    shape = _document_text_shape(version, source)
    if (
        not isinstance(value, dict)
        or set(value) != set(shape)
        or value["policy"] != shape["policy"]
        or value["source_sha256"] != source
        or value["scope"] != shape["scope"]
        or not isinstance(value["documents"], list)
    ):
        raise ValueError("Invalid document text binding")
    if value["status"] == "unconfirmed":
        if (
            value["documents"]
            or not isinstance(value["reason"], str)
            or not re.fullmatch(r"[a-z_]{1,80}", value["reason"])
        ):
            raise ValueError("Invalid unconfirmed document text")
        return
    if (
        value["status"] != "recorded"
        or value["reason"] is not None
        or report["inspection_complete"] is not True
        or report["structural_check"] != "passed"
    ):
        raise ValueError("Invalid recorded document text")
    content = report["content_evidence"]
    validate_content_evidence(content, source, policy=INSPECTION_POLICIES[version])
    if content["status"] != "recorded":
        raise ValueError("Document text requires complete source text")
    limits = report["policy"]["limits"]
    for name, ceiling in (
        ("max_members", 2048),
        ("max_records", 8192),
        ("max_name_chars", 512),
        ("max_xml_text_chars", 16 * 1024 * 1024),
    ):
        if type(limits[name]) is not int or not 1 <= limits[name] <= ceiling:
            raise ValueError("Invalid document text limits")
    rows = value["documents"]
    spine, documents, manifest = (report[name] for name in ("spine", "documents", "manifest"))
    if (
        any(not isinstance(entries, list) for entries in (spine, documents, manifest))
        or not 1 <= len(rows) == len(spine) == content["spine_documents"] <= limits["max_members"]
        or len(documents) > limits["max_members"]
        or sum(len(entries) for entries in (rows, spine, documents, manifest))
        > limits["max_records"]
    ):
        raise ValueError("Invalid document text counts")

    def path(value):
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= limits["max_name_chars"]
            or "\\" in value
            or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value)
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("Invalid document text path")
        return value

    resources = {}
    for document in documents:
        location = path(document["path"])
        digest = document["byte_sha256"]
        if (
            location in resources
            or not isinstance(digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
        ):
            raise ValueError("Invalid document text resource")
        resources[location] = digest
    spine_paths = {path(item["path"]) for item in spine}
    media = {}
    for item in manifest:
        location = path(item["path"])
        if location not in spine_paths:
            continue
        if location in media:
            raise ValueError("Ambiguous document text resource")
        media[location] = item["media_type"]
    seen = set()
    for index, (row, item) in enumerate(zip(rows, spine, strict=True)):
        if not isinstance(row, dict) or set(row) != {
            "path",
            "spine_index",
            "resource_sha256",
            "text_sha256",
            "text_chars",
        }:
            raise ValueError("Invalid document text row")
        location = path(row["path"])
        if (
            location in seen
            or location != item["path"]
            or location not in resources
            or media.get(location) not in {"application/xhtml+xml", "text/html"}
            or type(item["index"]) is not int
            or item["index"] != index
            or type(row["spine_index"]) is not int
            or row["spine_index"] != index
            or row["resource_sha256"] != resources[location]
            or not isinstance(row["text_sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", row["text_sha256"])
            or type(row["text_chars"]) is not int
            or not int(not current) <= row["text_chars"] <= limits["max_xml_text_chars"]
            or not row["text_chars"]
            and row["text_sha256"] != EMPTY_TEXT_SHA256
        ):
            raise ValueError("Invalid document text observation")
        seen.add(location)
    texts = [row["text_chars"] for row in rows if row["text_chars"]]
    if (
        not texts
        or sum(texts) + len(texts) - 1 != content["text_chars"]
        or content["text_chars"] > limits["max_xml_text_chars"]
        or current
        and content["empty_spine_documents"] != len(rows) - len(texts)
    ):
        raise ValueError("Invalid aggregate document text count")


def validate_document_text_evidence(report):
    """Validate capture and cross-field locators without reinterpreting old inspections."""
    try:
        _validate_document_text_evidence(report)
    except KeyError, TypeError, AttributeError:
        raise ValueError("Invalid document text evidence") from None
