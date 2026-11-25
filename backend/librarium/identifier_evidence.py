"""Bounded package identifier observations; scheme meaning belongs to comparison policy."""

from librarium.xml_names import XML_WHITESPACE, valid_ncname

OPF = "{http://www.idpf.org/2007/opf}"
DC = "{http://purl.org/dc/elements/1.1/}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SCHEMA_VERSION = "librarium.epub-identifiers.v1"
POLICY_VERSION = "librarium.epub-structure.v5"
HISTORICAL_POLICIES = {f"librarium.epub-structure.v{n}" for n in (1, 2, 3, 4)}
EVIDENCE_FIELDS = {
    "schema_version",
    "package_path",
    "package_sha256",
    "package_version",
    "unique_identifier",
    "prefix",
    "entries",
    "refinements",
}
ENTRY_FIELDS = {
    "source_index",
    "value",
    "id",
    "xml_id",
    "id_count",
    "xml_id_count",
    "opf_scheme",
    "text_only",
}
REFINEMENT_FIELDS = {
    "source_index",
    "property",
    "refines",
    "scheme",
    "value",
    "text_only",
    "target_id",
    "target_count",
    "target_source_index",
    "association",
}


class EvidenceRefused(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def metadata_scope(root):
    sections = root.findall(OPF + "metadata")
    if not sections:
        raise EvidenceRefused("missing_package_metadata")
    if len(sections) != 1:
        raise EvidenceRefused("multiple_package_metadata")
    metadata = sections[0]
    legacy = metadata.findall(OPF + "dc-metadata")
    if legacy:
        if (
            root.get("version") != "2.0"
            or len(legacy) != 1
            or any(element.tag.startswith(DC) for element in metadata)
        ):
            raise EvidenceRefused("unsupported_package_metadata")
        return metadata, legacy[0]
    return metadata, metadata


def capture_identifier_evidence(root, package, metadata, dc_parent, budget, resolve):
    nodes = list(root.iter())
    positions = {element: index for index, element in enumerate(nodes)}
    owners: dict[str, set[int]] = {}
    for index, element in enumerate(nodes):
        aliases = set()
        for name in ("id", XML_ID):
            value = element.get(name)
            if value is not None:
                budget.field(value)
                if value:
                    aliases.add(value)
        for value in aliases:
            owners.setdefault(value, set()).add(index)

    def attribute(element, name):
        value = element.get(name)
        return budget.field(value) if value is not None else None

    def text(element):
        value = "".join(element.itertext()).strip(XML_WHITESPACE)
        if len(value) > budget.policy.max_metadata_chars:
            raise EvidenceRefused("metadata_limit")
        return value

    identifier_nodes = {element for element in dc_parent if element.tag == DC + "identifier"}
    entries = []
    for element in dc_parent:
        if element not in identifier_nodes:
            continue
        ident, xml_id = attribute(element, "id"), attribute(element, XML_ID)
        entries.append(
            budget.record(
                {
                    "source_index": positions[element],
                    "value": text(element),
                    "id": ident,
                    "xml_id": xml_id,
                    "id_count": len(owners.get(ident, set())),
                    "xml_id_count": len(owners.get(xml_id, set())),
                    "opf_scheme": attribute(element, OPF + "scheme"),
                    "text_only": len(element) == 0,
                }
            )
        )
    refinements = []
    for element in metadata:
        if element.tag != OPF + "meta" or element.get("property") != "identifier-type":
            continue
        refines = attribute(element, "refines")
        target = resolve(refines) if refines else None
        if not valid_ncname(target):
            target = None
        targets = owners.get(target, set()) if target is not None else set()
        position = next(iter(targets)) if len(targets) == 1 else None
        association = (
            "unresolved"
            if not refines
            else "unsupported"
            if target is None
            else "ambiguous"
            if len(targets) > 1
            else "unresolved"
            if not targets
            else "identifier"
            if position is not None and nodes[position] in identifier_nodes
            else "other"
        )
        refinements.append(
            budget.record(
                {
                    "source_index": positions[element],
                    "property": budget.field(element.get("property")),
                    "refines": refines,
                    "scheme": attribute(element, "scheme"),
                    "value": text(element),
                    "text_only": len(element) == 0,
                    "target_id": target,
                    "target_count": len(targets),
                    "target_source_index": position,
                    "association": association,
                }
            )
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "package_path": budget.field(package["path"]),
        "package_sha256": package["byte_sha256"],
        "package_version": package["version"],
        "unique_identifier": attribute(root, "unique-identifier"),
        "prefix": attribute(root, "prefix"),
        "entries": entries,
        "refinements": refinements,
    }


def _string(value, limit, *, nullable=False):
    return value is None and nullable or isinstance(value, str) and len(value) <= limit


def _integer(value, maximum, *, minimum=0):
    return type(value) is int and minimum <= value <= maximum


def _reference(package_path, value, limits):
    from librarium.epub_inspection import InspectionPolicy, _Budget, _Refused, _resolve

    if not value:
        return None
    try:
        path, fragment = _resolve(package_path, value, _Budget(InspectionPolicy(**limits), {}))
    except _Refused:
        return None
    return fragment if path == package_path and valid_ncname(fragment) else None


def validate_identifier_evidence(report: dict) -> dict | None:
    try:
        version = report.get("policy", {}).get("version")
        evidence = report.get("identifier_evidence")
        if version in HISTORICAL_POLICIES:
            if evidence is not None:
                raise ValueError("Historical reports have no identifier declaration capture")
            return None
        if (
            version
            not in {
                POLICY_VERSION,
                "librarium.epub-structure.v6",
                "librarium.epub-structure.v7",
                "librarium.epub-structure.v8",
                "librarium.epub-structure.v9",
                "librarium.epub-structure.v10",
                "librarium.epub-structure.v11",
            }
            or type(report.get("inspection_complete")) is not bool
        ):
            raise ValueError("Unsupported identifier capture policy")
        if evidence is None and not report["inspection_complete"]:
            return None
        if not isinstance(evidence, dict) or evidence.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Identifier declaration capture is unavailable")
        _validate(report, evidence)
    except (KeyError, TypeError, AttributeError, IndexError) as error:
        raise ValueError("Identifier declaration capture is malformed") from error
    return evidence


def _validate(report, evidence):
    import re

    from librarium.epub_inspection import InspectionPolicy, _member_name, _Refused

    limits = report["policy"]["limits"]
    policy = InspectionPolicy(**limits)
    field_limit, text_limit = policy.max_field_chars, policy.max_metadata_chars
    node_limit, record_limit = policy.max_xml_nodes, policy.max_records
    package = report["package"]
    if (
        not EVIDENCE_FIELDS <= evidence.keys()
        or not isinstance(package, dict)
        or not _string(package.get("path"), field_limit)
        or not package.get("path")
        or package.get("version") not in {"2.0", "3.0"}
        or not isinstance(package.get("byte_sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", package["byte_sha256"])
        or evidence.get("package_path") != package["path"]
        or evidence.get("package_sha256") != package["byte_sha256"]
        or evidence.get("package_version") != package["version"]
        or not _string(evidence.get("unique_identifier"), field_limit, nullable=True)
        or not _string(evidence.get("prefix"), field_limit, nullable=True)
        or not isinstance(evidence.get("entries"), list)
        or not isinstance(evidence.get("refinements"), list)
        or len(evidence["entries"]) + len(evidence["refinements"]) > record_limit
    ):
        raise ValueError("Identifier capture provenance or bounds are invalid")
    try:
        _member_name(package["path"], policy)
    except _Refused as error:
        raise ValueError("Identifier package path is invalid") from error
    metadata = report["metadata"]
    if (
        not isinstance(metadata, list)
        or len(metadata) > record_limit
        or any(
            not isinstance(item, dict)
            or item.get("name") not in {"title", "creator", "language", "identifier"}
            or not _string(item.get("text"), text_limit)
            for item in metadata
        )
    ):
        raise ValueError("Package metadata is malformed")
    entries: dict[int, dict] = {}
    aliases: dict[str, tuple[int, int | None]] = {}
    previous = -1
    for item in evidence["entries"]:
        if (
            not isinstance(item, dict)
            or not ENTRY_FIELDS <= item.keys()
            or (
                not _integer(item.get("source_index"), node_limit - 1, minimum=2)
                or item["source_index"] <= previous
                or not _string(item.get("value"), text_limit)
                or type(item.get("text_only")) is not bool
                or any(
                    not _string(item.get(name), field_limit, nullable=True)
                    for name in ("id", "xml_id", "opf_scheme")
                )
            )
        ):
            raise ValueError("Identifier source record is malformed")
        for attr, count in (("id", "id_count"), ("xml_id", "xml_id_count")):
            if not _integer(item.get(count), node_limit, minimum=1 if item[attr] else 0) or (
                not item[attr] and item[count] != 0
            ):
                raise ValueError("Identifier alias count is invalid")
        if item["id"] == item["xml_id"] and item["id_count"] != item["xml_id_count"]:
            raise ValueError("Identifier alias counts disagree")
        previous = item["source_index"]
        entries[previous] = item
        for attr, count_name in (("id", "id_count"), ("xml_id", "xml_id_count")):
            value, count = item[attr], item[count_name]
            if not value:
                continue
            observation = (count, previous if count == 1 else None)
            if value in aliases and aliases[value] != observation:
                raise ValueError("Identifier aliases have inconsistent source counts")
            aliases[value] = observation
    if [item["value"] for item in evidence["entries"]] != [
        item["text"] for item in metadata if item["name"] == "identifier"
    ]:
        raise ValueError("Identifier capture differs from retained package metadata")
    previous = -1
    for item in evidence["refinements"]:
        if (
            not isinstance(item, dict)
            or not REFINEMENT_FIELDS <= item.keys()
            or (
                not _integer(item.get("source_index"), node_limit - 1, minimum=2)
                or item["source_index"] <= previous
                or item["source_index"] in entries
                or item.get("property") != "identifier-type"
                or not _string(item.get("value"), text_limit)
                or type(item.get("text_only")) is not bool
                or any(
                    not _string(item.get(name), field_limit, nullable=True)
                    for name in ("refines", "scheme", "target_id")
                )
                or not _integer(item.get("target_count"), node_limit)
                or item.get("association")
                not in {"identifier", "other", "ambiguous", "unresolved", "unsupported"}
            )
        ):
            raise ValueError("Identifier refinement is malformed")
        target = _reference(package["path"], item["refines"], limits)
        if item["target_id"] != target:
            raise ValueError("Refinement target differs from its recorded reference")
        count, position, association = (
            item["target_count"],
            item.get("target_source_index"),
            item["association"],
        )
        if (
            count == 1
            and not _integer(position, node_limit - 1)
            or count != 1
            and position is not None
            or association in {"identifier", "other"}
            and (count != 1 or not target)
            or association == "ambiguous"
            and (count < 2 or not target)
            or association in {"unresolved", "unsupported"}
            and count != 0
            or association == "unsupported"
            and (target is not None or not item["refines"])
            or association == "unresolved"
            and item["refines"]
            and target is None
            or association == "identifier"
            and position not in entries
            or association == "other"
            and position in entries
        ):
            raise ValueError("Refinement association is inconsistent")
        if target in aliases:
            expected_count, expected_position = aliases[target]
            if (
                expected_count != count
                or association == "other"
                or count == 1
                and position != expected_position
            ):
                raise ValueError("Refinement association conflicts with an identifier alias")
        if association == "identifier" and target not in aliases:
            raise ValueError("Refinement does not name its identifier")
        previous = item["source_index"]
