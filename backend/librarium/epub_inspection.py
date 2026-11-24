"""Pure, bounded structural evidence from caller-supplied EPUB bytes.

``inspect_bytes(data, expected_sha256, policy=None)`` returns JSON-safe facts in
archive/manifest/spine/document order. Malformed input and exhausted budgets return
failed findings; programmer errors (argument types, invalid digest/policy) raise.
``inspection_complete`` means this policy's checks finished, including on failure.
Partial facts on refusal are observations only. No result establishes identity,
ownership, content completeness, admission, or readiness. No prose samples,
proposed removals, timestamps, filesystem paths, or writer operations are produced.

Adapted from LF candidate a2a3692's bin/epub_content.py:29-38,118-207
(resolve/xml/package/inspect_epub), verified against Librarium's capture manifest.
The archive uses bin/epub_content.py, rather than the service path in the brief.
Source selection is provenance, not promotion of the candidate to a reviewed LF
baseline. ZIP streams replace LF's file/output interface; no upstream imports.

Policy v10 uses pinned libarchive's seekable ZIP reader, including bounded ZIP64,
stored/deflated regular members and relative package references. Library-exposed
names are checked; raw names may be normalized and central/local name agreement
is not established. Raw ZIP header conformance remains unchecked. Only closed, plain
HTML/XHTML DOCTYPEs are accepted without loading their DTDs. Internal subsets and
entity declarations are refused; HTML4 named characters are reported and decoded
from a fixed local table. It rejects xml:base/HTML base, remote package assets,
queries and ambiguous encodings. XHTML/HTML must be well-formed XML. Local
href/src/poster/data/xlink:href references and fragments are checked; XHTML HTTP(S)/mailto
hyperlinks are counted without fetching or returning their target attributes. CSS/script behavior,
media decoding, EPUB specification conformance and story completeness are outside
this slice. EPUBCheck and content acceptance always remain explicitly unchecked.

Only selected DC title/creator/language/identifier metadata and source heading,
anchor, navigation and semantic title/credit labels are returned, bounded per entry. Navigation keeps
source group ancestry without inferring contents structure or repair decisions.
Body word/media counts and source positions describe XML source, not rendered
visibility or narrative completeness. Versioned full-spine body text and resource
hashes supply comparison leads; they never authenticate a work or clear semantic
duplicates. Text-empty spine documents (image-only or blank pages) are counted, not
refused (content evidence v2). Document prose is omitted, apart from short title-like
lines recorded as contents observations. A separate bounded planner can derive a
read-only contents proposal from this evidence.
Oversize archives are refused before hashing
(source_sha256 is None; expected_sha256 remains bound).
The immutable policy may only tighten hard ceilings. Every selected policy limit
is returned with its version. XML byte/text/node/depth/attribute budgets cover
parsing; record/finding/serialized-output budgets cover reported facts. All ZIP
members are fully drained by the native reader for integrity checks, including
assets outside the manifest. The production file worker isolates this complete
inspection with process resource limits before loading the native reader.
Callers preserve/pin source bytes outside this module.
"""

import hashlib
import json
import posixpath
import re
from dataclasses import asdict, dataclass
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

POLICY_VERSION = "librarium.epub-structure.v10"
ARCHIVE_READER = {
    "library": "libarchive",
    "version": "3.8.10",
    "binding": "libarchive-c",
    "binding_version": "5.3",
    "format": "zip_seekable",
    "names": "library_exposed",
    "metadata": "library_exposed",
    "empty_member_crc": "not_verified",
    "raw_header_conformance": "not_checked",
}
UPSTREAM_REVISION = "a2a3692c3d864e133f5d7b80ed71c9983e810432"
UPSTREAM_SOURCE_SHA256 = "cf278f85461a297a4e62b9859063a97dc67e30393ab02b4f3233e0a2f6f07e72"
OPF = "{http://www.idpf.org/2007/opf}"
XHTML = "{http://www.w3.org/1999/xhtml}"
NCX = "{http://www.daisy.org/z3986/2005/ncx/}"
DC = "{http://purl.org/dc/elements/1.1/}"
EPUB_TYPE = "{http://www.idpf.org/2007/ops}type"
XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XLINK = "{http://www.w3.org/1999/xlink}href"
XML_MEDIA = {
    "application/xhtml+xml",
    "text/html",
    "image/svg+xml",
    "application/x-dtbncx+xml",
    "application/xml",
    "text/xml",
}
XML_SUFFIXES = {".xml", ".opf", ".xhtml", ".html", ".svg", ".ncx"}
HEADING_TAGS = {XHTML + f"h{level}" for level in range(1, 7)}
TEXT_BOUNDARIES = HEADING_TAGS | {
    XHTML + name
    for name in (
        "address",
        "article",
        "aside",
        "blockquote",
        "body",
        "br",
        "caption",
        "dd",
        "details",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "summary",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    )
}
MEDIA_TAGS = {
    XHTML + name for name in ("img", "audio", "video", "object", "embed", "iframe", "canvas")
} | {
    "{http://www.w3.org/2000/svg}svg",
    "{http://www.w3.org/2000/svg}image",
    "{http://www.w3.org/1998/Math/MathML}math",
}
OBSERVED_TAGS = HEADING_TAGS | {XHTML + name for name in ("p", "div", "b", "strong")}
SKIPPED_TEXT_TAGS = {XHTML + name for name in ("head", "script", "style")} | {
    "{http://www.w3.org/2000/svg}script",
    "{http://www.w3.org/2000/svg}style",
}


# The smallest report that still records why inspection stopped; v10 raised it from 4096.
ENVELOPE_BYTES = 5120


@dataclass(frozen=True)
class InspectionPolicy:
    max_archive_bytes: int = 32 * 1024 * 1024
    max_members: int = 2048
    max_member_bytes: int = 8 * 1024 * 1024
    max_expanded_bytes: int = 64 * 1024 * 1024
    max_expansion_ratio: int = 200
    max_read_bytes: int = 64 * 1024 * 1024
    max_name_chars: int = 512
    max_field_chars: int = 512
    max_metadata_chars: int = 256
    max_xml_nodes: int = 100_000
    max_xml_depth: int = 64
    max_xml_text_chars: int = 16 * 1024 * 1024
    max_xml_attributes: int = 64
    max_attribute_chars: int = 4096
    max_records: int = 8192
    max_findings: int = 128
    max_output_bytes: int = 1024 * 1024

    def __post_init__(self):
        for name, value in asdict(self).items():
            ceiling = getattr(InspectionPolicy, name)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError(f"Invalid inspection policy limit: {name}")
        if self.max_output_bytes < ENVELOPE_BYTES:
            raise ValueError(
                f"max_output_bytes must allow the bounded report envelope ({ENVELOPE_BYTES})"
            )


class _Refused(Exception):
    def __init__(self, code: str):
        self.code = code


class _Budget:
    def __init__(self, policy: InspectionPolicy, report: dict):
        self.policy = policy
        self.report = report
        self.records = 0
        self.nodes = 0
        self.text_chars = 0
        self.read_bytes = 0
        self.document_text: dict | None = None
        self.contents_blocks: dict[str, list[dict]] = {}
        self.observation_records = 0

    def record(self, value: dict) -> dict:
        self.records += 1
        if self.records > self.policy.max_records:
            raise _Refused("record_limit")
        return value

    def field(self, value: str) -> str:
        if len(value) > self.policy.max_field_chars:
            raise _Refused("field_limit")
        return value

    def finding(self, code: str, path: str | None = None, severity: str = "error"):
        if len(self.report["findings"]) >= self.policy.max_findings:
            self.report["findings_truncated"] = True
            raise _Refused("finding_limit")
        item = {"code": code, "severity": severity}
        if path is not None:
            item["path"] = path
        self.report["findings"].append(item)

    def fatal(self, code: str):
        finding = {"code": code, "severity": "error"}
        if len(self.report["findings"]) >= self.policy.max_findings:
            self.report["findings"][-1] = finding
            self.report["findings_truncated"] = True
        else:
            self.report["findings"].append(finding)


def _member_name(name: str, policy: InspectionPolicy) -> str:
    if (
        not name
        or len(name) > policy.max_name_chars
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
        or any(char in name for char in "\\:%?#")
        or name.endswith("//")
        or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))
    ):
        raise _Refused("unsafe_zip_member")
    return name


class _XMLBuilder(ET.TreeBuilder):
    def __init__(self, budget: _Budget):
        super().__init__()
        self.budget = budget
        self.depth = 0

    def doctype(self, name, pubid, system):
        from librarium.xml_policy import doctype

        doctype(name, pubid, system)

    def start(self, tag, attrs):
        self.depth += 1
        self.budget.nodes += 1
        policy = self.budget.policy
        if self.depth > policy.max_xml_depth:
            raise _Refused("xml_depth_limit")
        if self.budget.nodes > policy.max_xml_nodes:
            raise _Refused("xml_nodes_limit")
        if len(attrs) > policy.max_xml_attributes:
            raise _Refused("xml_attributes_limit")
        if len(tag) > policy.max_attribute_chars or any(
            len(key) + len(value) > policy.max_attribute_chars for key, value in attrs.items()
        ):
            raise _Refused("xml_attributes_limit")
        if XML_BASE in attrs or tag == XHTML + "base":
            raise _Refused("unsupported_base_reference")
        return super().start(tag, attrs)

    def end(self, tag):
        self.depth -= 1
        return super().end(tag)

    def data(self, data):
        self.budget.text_chars += len(data)
        if self.budget.text_chars > self.budget.policy.max_xml_text_chars:
            raise _Refused("xml_text_limit")
        return super().data(data)


def _xml(data: bytes, budget: _Budget) -> ET.Element:
    from xml.parsers import expat

    from librarium.xml_policy import UnsafeDTD, guard, prepared

    data, entities = prepared(data)
    try:
        guard(data)
    except UnsafeDTD:
        raise _Refused("xml_dtd_forbidden") from None
    except LookupError, ValueError:
        raise _Refused("invalid_xml") from None
    except expat.ExpatError:
        raise ET.ParseError from None
    if (
        entities
        and "findings" in budget.report
        and not any(f["code"] == "named_html_entities" for f in budget.report["findings"])
    ):
        budget.finding("named_html_entities", severity="warning")
    parser = ET.XMLParser(target=_XMLBuilder(budget))
    try:
        for offset in range(0, len(data), 16384):
            parser.feed(data[offset : offset + 16384])
        return parser.close()
    except LookupError, ValueError:
        raise _Refused("invalid_xml") from None


def _resolve(base: str, href: str, budget: _Budget) -> tuple[str | None, str]:
    if not href or href != href.strip() or any(ord(c) < 32 or ord(c) == 127 for c in href):
        raise _Refused("unsafe_reference")
    budget.field(href)
    if re.search(r"%(?![0-9a-fA-F]{2})", href):
        raise _Refused("unsafe_reference")
    try:
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc:
            if parsed.scheme.lower() in {"https", "http", "mailto"}:
                return None, ""
            raise _Refused("unsafe_reference")
        if parsed.query or "?" in href.split("#", 1)[0]:
            raise _Refused("unsafe_reference")
        path = unquote(parsed.path, errors="strict")
        fragment = unquote(parsed.fragment, errors="strict")
    except ValueError, UnicodeError:
        raise _Refused("unsafe_reference") from None
    if any(ord(c) < 32 or ord(c) == 127 for c in path + fragment):
        raise _Refused("unsafe_reference")
    if path.startswith("/") or any(c in path for c in "\\:%?#"):
        raise _Refused("unsafe_reference")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(base), path)) if path else base
    try:
        _member_name(resolved, budget.policy)
    except _Refused:
        raise _Refused("unsafe_reference") from None
    return resolved, budget.field(fragment)


def _package_reference(base: str, href: str, budget: _Budget) -> str:
    try:
        path, fragment = _resolve(base, href, budget)
    except _Refused as error:
        if error.code == "field_limit":
            raise
        raise _Refused("unsafe_package_reference") from None
    if path is None or fragment or not href or "#" in href:
        raise _Refused("unsafe_package_reference")
    return path


def _metadata(root: ET.Element, budget: _Budget):
    from librarium.identifier_evidence import (
        EvidenceRefused,
        capture_identifier_evidence,
        metadata_scope,
    )

    try:
        metadata, dc_parent = metadata_scope(root)
    except EvidenceRefused as error:
        raise _Refused(error.code) from None
    for element in dc_parent:
        if element.tag not in {
            DC + name for name in ("title", "creator", "language", "identifier")
        }:
            continue
        text = "".join(element.itertext()).strip(" \t\r\n")
        if len(text) > budget.policy.max_metadata_chars:
            raise _Refused("metadata_limit")
        budget.report["metadata"].append(
            budget.record({"name": element.tag[len(DC) :], "text": text})
        )

    def resolve(refines):
        try:
            path, fragment = _resolve(budget.report["package"]["path"], refines, budget)
        except _Refused as error:
            if error.code == "field_limit":
                raise
            return None
        return fragment if path == budget.report["package"]["path"] and fragment else None

    try:
        budget.report["identifier_evidence"] = capture_identifier_evidence(
            root, budget.report["package"], metadata, dc_parent, budget, resolve
        )
    except EvidenceRefused as error:
        raise _Refused(error.code) from None


def _chapter_number(text: str) -> int | None:
    if len(text) > 64:
        return None
    match = re.fullmatch(r"\s*chapter\s+(\d{1,6})\s*", text, re.IGNORECASE)
    return int(match[1]) if match else None


def _label(element: ET.Element | None, budget: _Budget) -> str:
    if element is None:
        return ""
    parts = []
    stack = [(element, False)]
    while stack:
        node, tail = stack.pop()
        if tail:
            if node.tag in TEXT_BOUNDARIES:
                parts.append(" ")
            parts.append(node.tail or "")
            continue
        if node.tag in SKIPPED_TEXT_TAGS:
            continue
        if node.tag in TEXT_BOUNDARIES:
            parts.append(" ")
        parts.append(node.text or "")
        for child in reversed(node):
            stack.append((child, True))
            stack.append((child, False))
    return budget.field(" ".join("".join(parts).split()))


@dataclass
class _BodyCounts:
    words: int = 0
    non_heading_words: int = 0
    media: int = 0
    in_word: bool = False
    in_non_heading_word: bool = False

    def boundary(self):
        self.in_word = self.in_non_heading_word = False

    def text(self, text: str | None, *, heading: bool):
        if not text:
            return
        words = sum(1 for _ in re.finditer(r"\S+", text))
        self.words += words - (self.in_word and not text[0].isspace())
        self.in_word = not text[-1].isspace()
        if not heading:
            self.non_heading_words += words - (self.in_non_heading_word and not text[0].isspace())
            self.in_non_heading_word = self.in_word


def _li_label_element(element: ET.Element) -> ET.Element | None:
    return next((child for child in element if child.tag in {XHTML + "a", XHTML + "span"}), None)


def _li_label(element: ET.Element, budget: _Budget) -> str:
    return _label(_li_label_element(element), budget)


def _document(path: str, body: bytes, root: ET.Element, budget: _Budget) -> tuple[dict, set[str]]:
    facts = budget.record(
        {
            "path": path,
            "byte_sha256": hashlib.sha256(body).hexdigest(),
            "headings": [],
            "links": [],
            "anchors": [],
            "body_word_count": None,
            "non_heading_word_count": None,
            "media_count": None,
        }
    )
    ids: set[str] = set()
    bodies = root.findall(XHTML + "body") if root.tag == XHTML + "html" else []
    body_element = bodies[0] if len(bodies) == 1 else None
    counts = _BodyCounts()
    source_index = -1
    source_indexes: dict[ET.Element, int] = {}
    positions: dict[ET.Element, dict] = {}
    heading_elements: list[ET.Element] = []
    stack: list[
        tuple[ET.Element, bool, int | None, bool, bool, tuple[tuple[str, ET.Element | None], ...]]
    ] = [(root, False, None, False, False, ())]
    while stack:
        element, exiting, heading_index, parent_active, parent_skipped, groups = stack.pop()
        skipped = parent_skipped or element.tag in SKIPPED_TEXT_TAGS
        active = (parent_active or element is body_element) and not skipped
        if exiting:
            if active and element.tag in TEXT_BOUNDARIES:
                counts.boundary()
            if parent_active:
                counts.text(element.tail, heading=heading_index is not None)
            continue
        source_index += 1
        source_indexes[element] = source_index
        stack.append((element, True, heading_index, parent_active, parent_skipped, groups))
        if active and element.tag in TEXT_BOUNDARIES:
            counts.boundary()
        offsets = {
            "word_offset": counts.words if active else None,
            "non_heading_word_offset": counts.non_heading_words if active else None,
            "media_offset": counts.media if active else None,
        }
        if active and element.tag in OBSERVED_TAGS:
            positions[element] = {"source_index": source_index, **offsets}
        if element.tag == XHTML + "li":
            label_element = None if skipped else _li_label_element(element)
            groups = (*groups, (_label(label_element, budget), label_element))
        element_ids: set[str] = set()
        for attribute, ident in element.attrib.items():
            if (
                attribute not in {"id", XML_ID}
                and not (attribute == "name" and element.tag == XHTML + "a")
                or not ident
            ):
                continue
            if ident in element_ids:
                continue
            element_ids.add(ident)
            budget.field(ident)
            if ident in ids:
                budget.finding("duplicate_document_id", path)
            ids.add(ident)
            facts["anchors"].append(
                budget.record({"id": ident, "source_index": source_index, **offsets})
            )
        if element.tag in HEADING_TAGS:
            heading_index = len(facts["headings"])
            heading_elements.append(element)
            label = "" if skipped else _label(element, budget)
            facts["headings"].append(
                budget.record(
                    {
                        "level": int(element.tag[-1]),
                        "id": element.get("id") or element.get(XML_ID),
                        "chapter_number": _chapter_number(label),
                        "label": label,
                        "source_index": source_index,
                        "word_count": len(label.split()),
                        **offsets,
                    }
                )
            )
        for attribute in ("href", "src", "poster", "data", XLINK):
            href = element.get(attribute)
            if not href:
                continue
            try:
                target, fragment = _resolve(path, href, budget)
            except _Refused as error:
                if error.code == "field_limit":
                    raise
                budget.finding("unsafe_resource_link", path)
                continue
            if target is None and not (element.tag == XHTML + "a" and attribute == "href"):
                budget.finding("remote_resource_reference", path)
            facts["links"].append(
                budget.record(
                    {
                        "tag": budget.field(element.tag.rsplit("}", 1)[-1]),
                        "attribute": "xlink:href" if attribute == XLINK else attribute,
                        "target_path": target,
                        "fragment": fragment,
                        "external": target is None,
                        "heading_index": heading_index,
                        "source_index": source_index,
                        "word_offset": offsets["word_offset"],
                        **(
                            {
                                "label": "" if skipped else _label(element, budget),
                                "ancestors": [label for label, _ in groups[:-1]],
                                "ancestor_sources": [
                                    budget.record(
                                        {
                                            "label": label,
                                            "source_index": source_indexes.get(label_element)
                                            if label_element is not None
                                            else None,
                                        }
                                    )
                                    for label, label_element in groups[:-1]
                                ],
                            }
                            if element.tag == XHTML + "a"
                            else {}
                        ),
                    }
                )
            )
        if active:
            if element.tag in MEDIA_TAGS or (
                element.tag == XHTML + "input" and element.get("type", "").lower() == "image"
            ):
                counts.media += 1
            counts.text(element.text, heading=heading_index is not None)
        stack.extend(
            (child, False, heading_index, active, skipped, groups) for child in reversed(element)
        )
    if body_element is not None:
        facts.update(
            body_word_count=counts.words,
            non_heading_word_count=counts.non_heading_words,
            media_count=counts.media,
        )
        from librarium.contents_observations import observe

        signals, blocks, flags = observe(
            body_element,
            positions,
            facts["headings"],
            heading_elements,
            XHTML,
            TEXT_BOUNDARIES,
            SKIPPED_TEXT_TAGS,
        )
        for heading, flag in zip(facts["headings"], flags, strict=True):
            heading.update(flag)
        if signals:
            facts["contents_signals"] = budget.record(signals)
        for block in blocks:
            for key in ("label", "class", "id"):
                if key in block:
                    budget.field(block[key])
        budget.contents_blocks[path] = blocks
    facts["source_element_count"] = source_index + 1
    return facts, ids


def _navigation(root: ET.Element, path: str, kind: str, budget: _Budget):
    entries = budget.report["navigation"]["entries"]
    before = len(entries)
    scope_tag, group_tag, link_tag, attribute = (
        (XHTML + "nav", XHTML + "li", XHTML + "a", "href")
        if kind == "nav"
        else (NCX + "navMap", NCX + "navPoint", NCX + "content", "src")
    )
    stack: list[tuple[ET.Element, bool, tuple[str, ...]]] = [(root, False, ())]
    while stack:
        element, in_scope, groups = stack.pop()
        if element.tag == scope_tag and (
            kind != "nav" or "toc" in element.get(EPUB_TYPE, "").split()
        ):
            in_scope = True
        if in_scope and element.tag == group_tag:
            groups = (
                *groups,
                _li_label(element, budget)
                if kind == "nav"
                else _label(element.find(NCX + "navLabel"), budget),
            )
        stack.extend((child, in_scope, groups) for child in reversed(element))
        if not in_scope or element.tag != link_tag:
            continue
        label = _label(element, budget) if kind == "nav" else groups[-1] if groups else ""
        try:
            target, fragment = _resolve(path, element.get(attribute, ""), budget)
        except _Refused as error:
            if error.code == "field_limit":
                raise
            budget.finding("invalid_navigation_target", path)
            continue
        if target is None:
            budget.finding("invalid_navigation_target", path)
        else:
            entries.append(
                budget.record(
                    {
                        "path": path,
                        "target_path": target,
                        "fragment": fragment,
                        "label": label,
                        "kind": kind,
                        "ancestors": list(groups[:-1]),
                    }
                )
            )
    if len(entries) == before:
        budget.finding("empty_navigation", path)


def _inspect(data: bytes, budget: _Budget):
    from librarium.content_evidence import capture, capture_document_text
    from librarium.epub_archive import ArchiveRefused, read_archive

    try:
        archive = read_archive(data, budget.policy)
    except ArchiveRefused as error:
        raise _Refused(error.code) from None
    budget.report["archive"] = {
        "member_count": len(archive.members),
        "expanded_bytes": sum(member.size for member in archive.members.values()),
    }
    container_member = archive.members.get("META-INF/container.xml")
    if container_member is None or container_member.is_dir():
        raise _Refused("missing_container")
    container = _xml(archive.read("META-INF/container.xml"), budget)
    if container.tag != "{urn:oasis:names:tc:opendocument:xmlns:container}container":
        raise _Refused("invalid_container")
    rootfiles = container.findall(
        "{urn:oasis:names:tc:opendocument:xmlns:container}rootfiles/"
        "{urn:oasis:names:tc:opendocument:xmlns:container}rootfile"
    )
    if not rootfiles:
        raise _Refused("missing_package_rootfile")
    if len(rootfiles) != 1:
        raise _Refused("multiple_renditions_not_supported")
    # full-path is container-root-relative, unlike manifest/document references.
    raw_path = rootfiles[0].get("full-path", "")
    package_path = _package_reference("", raw_path, budget)
    if package_path != raw_path:
        raise _Refused("unsafe_package_reference")
    package_member = archive.members.get(package_path)
    if package_member is None or package_member.is_dir():
        raise _Refused("missing_package_document")
    package_bytes = archive.read(package_path)
    root = _xml(package_bytes, budget)
    if root.tag != OPF + "package" or root.get("version") not in {"2.0", "3.0"}:
        raise _Refused("unsupported_package")
    budget.report["package"] = {
        "path": package_path,
        "version": root.get("version"),
        "byte_sha256": hashlib.sha256(package_bytes).hexdigest(),
    }
    _metadata(root, budget)
    manifest: dict[str, dict] = {}
    for element in root.findall(OPF + "manifest/" + OPF + "item"):
        ident = budget.field(element.get("id", ""))
        if not ident or ident in manifest:
            raise _Refused("duplicate_manifest_id" if ident else "missing_manifest_id")
        path = _package_reference(package_path, element.get("href", ""), budget)
        entry = budget.record(
            {
                "id": ident,
                "path": path,
                "media_type": budget.field(element.get("media-type", "")),
                "properties": budget.field(element.get("properties", "")).split(),
            }
        )
        manifest[ident] = entry
        budget.report["manifest"].append(entry)
        if path not in archive.members or archive.members[path].is_dir():
            budget.finding("missing_manifest_resource", path)
    if not manifest:
        raise _Refused("empty_manifest")
    docs: dict[str, tuple[dict, set[str]]] = {}
    trees: dict[str, ET.Element] = {}
    for item in manifest.values():
        path = item["path"]
        if path not in archive.members or archive.members[path].is_dir():
            continue
        if item["media_type"] in XML_MEDIA or posixpath.splitext(path)[1].lower() in XML_SUFFIXES:
            tree = trees.get(path)
            if tree is None:
                body = archive.read(path)
                try:
                    tree = _xml(body, budget)
                except ET.ParseError:
                    budget.finding("invalid_xml", path)
                    continue
                trees[path] = tree
            expected_root = {
                "application/xhtml+xml": XHTML + "html",
                "text/html": XHTML + "html",
                "image/svg+xml": "{http://www.w3.org/2000/svg}svg",
                "application/x-dtbncx+xml": NCX + "ncx",
            }.get(item["media_type"])
            if expected_root and tree.tag != expected_root:
                budget.finding("unexpected_document_root", path)
                continue
            if path not in docs:
                docs[path] = _document(path, archive.read(path), tree, budget)
                budget.report["documents"].append(docs[path][0])
    for item in manifest.values():
        path = item["path"]
        if "nav" in item["properties"]:
            budget.report["navigation"]["nav_paths"].append(path)
            if (
                item["media_type"] != "application/xhtml+xml"
                or path in trees
                and trees[path].tag != XHTML + "html"
            ):
                budget.finding("unexpected_document_root", path)
            elif path in trees:
                _navigation(trees[path], path, "nav", budget)
            else:
                budget.finding("unreadable_navigation", path)
        if item["media_type"] == "application/x-dtbncx+xml":
            budget.report["navigation"]["ncx_paths"].append(path)
            if path in trees:
                _navigation(trees[path], path, "ncx", budget)
            else:
                budget.finding("unreadable_navigation", path)
    navigation = budget.report["navigation"]
    if not navigation["nav_paths"] and not navigation["ncx_paths"]:
        budget.finding("missing_navigation")
    references: list[dict] = []
    for doc, _ in docs.values():
        elements = list(trees[doc["path"]].iter())
        references.extend(
            {
                **link,
                "page_hyperlink": trees[doc["path"]].tag == XHTML + "html"
                and elements[link["source_index"]].tag == XHTML + "a",
            }
            for link in doc["links"]
        )
    references.extend({**link, "external": False} for link in navigation["entries"])
    for link in references:
        path = link["target_path"]
        if link["external"]:
            navigation["external_link_count"] += 1
        elif path not in archive.members or archive.members[path].is_dir():
            correctable = link.get("page_hyperlink", False) and link.get("attribute") == "href"
            if not correctable or not any(
                f["code"] == "missing_link_resource" and f["severity"] == "warning"
                for f in budget.report["findings"]
            ):
                budget.finding(
                    "missing_link_resource", severity="warning" if correctable else "error"
                )
        elif link["fragment"]:
            if path not in docs:
                budget.finding("uncheckable_fragment_target")
            elif link["fragment"] not in docs[path][1]:
                budget.finding("missing_link_fragment", path)
    spine = root.find(OPF + "spine")
    refs = [] if spine is None else spine.findall(OPF + "itemref")
    if not refs:
        budget.finding("empty_spine")
    seen: set[str] = set()
    for index, ref in enumerate(refs):
        ident = budget.field(ref.get("idref", ""))
        spine_item = manifest.get(ident)
        if spine_item is None:
            budget.finding("missing_spine_manifest_id")
            continue
        path = spine_item["path"]
        linear = ref.get("linear", "yes")
        if linear not in {"yes", "no"}:
            budget.finding("invalid_spine_linear", path)
            linear = "invalid"
        budget.report["spine"].append(
            budget.record(
                {
                    "index": index,
                    "idref": ident,
                    "path": path,
                    "linear": linear,
                }
            )
        )
        if path not in docs or spine_item["media_type"] not in {
            "application/xhtml+xml",
            "text/html",
            "image/svg+xml",
        }:
            budget.finding("unreadable_spine_document", path)
        if path in seen:
            budget.finding("repeated_spine_document", path, "warning")
        seen.add(path)
    for path, info in archive.members.items():
        if (
            path not in trees
            and not info.is_dir()
            and posixpath.splitext(path)[1].lower() in XML_SUFFIXES
        ):
            _xml(archive.read(path), budget)
    budget.report["inspection_complete"] = True
    budget.report["content_evidence"] = budget.record(
        capture(budget.report, trees, archive, TEXT_BOUNDARIES, XHTML)
    )
    from librarium.source_attribution import capture as capture_attribution

    budget.report["source_attribution"] = budget.record(
        capture_attribution(budget.report, trees, budget)
    )
    _attach_contents_observations(budget)
    # Optional rows must not consume capacity needed by structure and contents planning.
    budget.document_text = capture_document_text(
        budget.report, trees, TEXT_BOUNDARIES, XHTML, lambda row: row
    )


def _attach_contents_observations(budget: _Budget):
    """Optional short-line observations, recorded only while they fit the shared budgets.

    They rank below structure and above document text: when the plan or the final report
    later exhausts a budget, ``_detach_contents_observations`` removes them and replans.
    """
    from librarium.contents_observations import observed, unobserved

    report = budget.report
    documents = [doc for doc in report["documents"] if doc["path"] in budget.contents_blocks]
    blocks = sum(len(budget.contents_blocks[doc["path"]]) for doc in documents)
    budget.observation_records = budget.records
    if budget.records + blocks + 1 > budget.policy.max_records:
        report["contents_observations"] = budget.record(unobserved("record_limit"))
        return
    size = len(json.dumps(report, ensure_ascii=True).encode()) + sum(
        len(json.dumps(budget.contents_blocks[doc["path"]], ensure_ascii=True).encode()) + 12
        for doc in documents
    )
    if size > budget.policy.max_output_bytes:
        report["contents_observations"] = budget.record(unobserved("output_bytes_limit"))
        return
    for doc in documents:
        doc["blocks"] = [budget.record(block) for block in budget.contents_blocks[doc["path"]]]
    report["contents_observations"] = budget.record(observed(blocks))


def _detach_contents_observations(budget: _Budget, reason: str) -> bool:
    """Release attached observations and their records; False when none were attached."""
    from librarium.contents_observations import unobserved

    report = budget.report
    if report["contents_observations"]["status"] != "recorded":
        return False
    for doc in report["documents"]:
        doc.pop("blocks", None)
    budget.records = budget.observation_records
    report["contents_observations"] = budget.record(unobserved(reason))
    return True


def _plan(report: dict, budget: _Budget) -> dict:
    """The contents plan; the partial plan's records are released with the observations."""
    from librarium.contents_planning import contents_plan

    try:
        return contents_plan(report, record=budget.record)
    except _Refused as error:
        if error.code != "record_limit" or not _detach_contents_observations(budget, error.code):
            raise
    return contents_plan(report, record=budget.record)


def inspect_bytes(
    data: bytes,
    expected_sha256: str,
    policy: InspectionPolicy | None = None,
) -> dict:
    """Inspect an immutable byte snapshot pinned by a lowercase SHA-256 hex digest."""
    if not isinstance(data, bytes):
        raise TypeError("data must be immutable bytes")
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise ValueError("expected_sha256 must be a lowercase SHA-256 hex digest")
    if policy is not None and not isinstance(policy, InspectionPolicy):
        raise TypeError("policy must be an InspectionPolicy")
    policy = policy if policy is not None else InspectionPolicy()
    from librarium.content_evidence import unconfirmed, unconfirmed_document_text
    from librarium.contents_observations import unobserved
    from librarium.source_attribution import unconfirmed as attribution_unconfirmed

    report: dict = {
        "schema_version": "librarium.epub-inspection.v1",
        "source_sha256": None,
        "expected_sha256": expected_sha256,
        "policy": {"version": POLICY_VERSION, "limits": asdict(policy)},
        "upstream": {
            "repository": "https://github.com/jshauns81/library-finish.git",
            "revision": UPSTREAM_REVISION,
            "source": "bin/epub_content.py",
            "source_sha256": UPSTREAM_SOURCE_SHA256,
        },
        "archive_reader": dict(ARCHIVE_READER),
        "archive": None,
        "package": None,
        "metadata": [],
        "identifier_evidence": None,
        "manifest": [],
        "spine": [],
        "documents": [],
        "navigation": {"nav_paths": [], "ncx_paths": [], "entries": [], "external_link_count": 0},
        "findings": [],
        "findings_truncated": False,
        "inspection_complete": False,
        "structural_check": "failed",
        "epubcheck": "not_run",
        "content_acceptance": "not_checked",
        "content_evidence": unconfirmed(None, "inspection_incomplete"),
        "document_text_evidence": unconfirmed_document_text(None, "inspection_incomplete"),
        "source_attribution": attribution_unconfirmed(None, "inspection_incomplete"),
        "contents_observations": unobserved("inspection_incomplete"),
        "ready": False,
    }
    budget = _Budget(policy, report)
    try:
        if len(data) > policy.max_archive_bytes:
            raise _Refused("archive_bytes_limit")
        report["source_sha256"] = hashlib.sha256(data).hexdigest()
        if report["source_sha256"] != expected_sha256:
            raise _Refused("source_hash_mismatch")
        _inspect(data, budget)
    except _Refused as error:
        budget.fatal(error.code)
    except ET.ParseError:
        budget.fatal("invalid_xml")
    report["structural_check"] = (
        "passed"
        if report["inspection_complete"]
        and not any(f["severity"] == "error" for f in report["findings"])
        else "failed"
    )
    from librarium.contents_planning import held_plan

    def plan():
        # Replanning after a budget fallback must reconsider the original defect.
        for finding in report["findings"]:
            if finding["code"] == "empty_navigation":
                finding["severity"] = "error"
        try:
            report["contents_plan"] = _plan(report, budget)
        except _Refused as error:
            budget.fatal(error.code)
            report["inspection_complete"] = False
            report["structural_check"] = "failed"
            report["contents_plan"] = held_plan(report, error.code)
        if (
            report["inspection_complete"]
            and not report["findings_truncated"]
            and report["contents_plan"]["decision"] == "propose"
            and report["contents_plan"]["entries"]
            and not any(
                f["severity"] == "error" and f["code"] != "empty_navigation"
                for f in report["findings"]
            )
        ):
            for finding in report["findings"]:
                if finding["code"] == "empty_navigation":
                    finding["severity"] = "warning"
        report["structural_check"] = (
            "passed"
            if report["inspection_complete"]
            and not any(f["severity"] == "error" for f in report["findings"])
            else "failed"
        )

    plan()
    candidate = budget.document_text
    if candidate is not None and report["structural_check"] == "passed":
        report["document_text_evidence"] = candidate
        if candidate["status"] == "recorded":
            needed = len(candidate["documents"]) + 1
            if budget.records + needed > policy.max_records:
                report["document_text_evidence"] = unconfirmed_document_text(
                    report["source_sha256"], "record_limit"
                )
            elif len(json.dumps(report, ensure_ascii=True).encode()) > policy.max_output_bytes:
                report["document_text_evidence"] = unconfirmed_document_text(
                    report["source_sha256"], "output_bytes_limit"
                )
            else:
                for row in candidate["documents"]:
                    budget.record(row)
                budget.record(candidate)
    if (
        report["inspection_complete"]
        and len(json.dumps(report, ensure_ascii=True).encode()) > policy.max_output_bytes
        and _detach_contents_observations(budget, "output_bytes_limit")
    ):
        plan()
    if len(json.dumps(report, ensure_ascii=True).encode()) > policy.max_output_bytes:
        for field in ("metadata", "manifest", "spine", "documents"):
            report[field] = []
        report["archive"] = report["package"] = None
        report["identifier_evidence"] = None
        report["navigation"] = {
            "nav_paths": [],
            "ncx_paths": [],
            "entries": [],
            "external_link_count": 0,
        }
        report["findings"] = [{"code": "output_bytes_limit", "severity": "error"}]
        report["findings_truncated"] = True
        report["contents_observations"] = unobserved("output_bytes_limit")
        report["inspection_complete"] = False
        report["structural_check"] = "failed"
        report["contents_plan"] = held_plan(report, "output_bytes_limit")
    if not report["inspection_complete"] or report["structural_check"] != "passed":
        report["content_evidence"] = unconfirmed(report["source_sha256"], "inspection_failed")
        report["document_text_evidence"] = unconfirmed_document_text(
            report["source_sha256"], "inspection_failed"
        )
        report["source_attribution"] = attribution_unconfirmed(
            report["source_sha256"], "inspection_failed"
        )
    return report
