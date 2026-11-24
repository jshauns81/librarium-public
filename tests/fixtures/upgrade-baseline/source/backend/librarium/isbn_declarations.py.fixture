"""Interpret a bounded subset of captured declarations without acquiring new source facts."""

import re
from urllib.parse import urlsplit

from librarium.xml_names import XML_WHITESPACE, valid_ncname

ONIX = "http://www.editeur.org/ONIX/book/codelists/current.html#"


def _prefixes(raw):
    result = {"onix": ONIX}
    if raw is None:
        return result
    value = raw.strip(XML_WHITESPACE)
    if not value:
        return None
    seen = set()
    position = 0
    while position < len(value):
        match = re.match(r"([^ \t\r\n:]+): +([^ \t\r\n]+)", value[position:])
        if match is None:
            return None
        name, iri = match.groups()
        if not valid_ncname(name) or name in seen:
            return None
        seen.add(name)
        result[name] = iri
        position += match.end()
        if position < len(value):
            separator = re.match(r"[ \t\r\n]+", value[position:])
            if separator is None:
                return None
            position += separator.end()
    return result


def _scheme(raw, prefixes):
    if raw is None or prefixes is None or ":" not in raw:
        return None
    prefix, reference = raw.split(":", 1)
    if (
        prefix not in prefixes
        or not reference
        or reference.startswith("/")
        or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in raw)
        or re.search(r"%(?![0-9a-fA-F]{2})", reference)
    ):
        return None
    try:
        parsed = urlsplit(reference)
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc:
        return None
    return prefixes[prefix] + reference


def _entry(value, observation, refinements, evidence, canonical):
    result = {
        "source": value,
        "canonical_isbn13": None,
        "status": "unsupported",
        "editions": [],
        "basis": None,
        "reason_codes": [],
        "source_position": None,
        "declarations": [],
    }
    urn = value[:9].lower() == "urn:isbn:"
    payload = value[9:] if urn else value
    urn_number = canonical(payload) if urn and not any(c in payload for c in "#?") else None
    number = None
    types: list[tuple[int | None, str]] = []
    issues = []
    if observation is None:
        result["reason_codes"].append("legacy_declarations_not_captured")
    else:
        result["source_position"] = {
            "path": evidence["package_path"],
            "document_sha256": evidence["package_sha256"],
            "source_index": observation["source_index"],
        }
        if not observation["text_only"]:
            result["reason_codes"] = ["identifier_not_text"]
            return result
        scheme = observation["opf_scheme"]
        if scheme is not None:
            result["declarations"].append(
                {
                    "kind": "opf_scheme",
                    "source_index": observation["source_index"],
                    "value": scheme,
                    "scheme": None,
                    "scheme_iri": None,
                    "refines": None,
                    "association": "identifier",
                }
            )
            if evidence["package_version"] != "2.0":
                issues.append("unsupported_scheme_version")
            elif scheme.strip(XML_WHITESPACE).lower() == "isbn":
                types.append((None, "opf_scheme"))
            else:
                issues.append("unsupported_opf_scheme")
        prefixes = _prefixes(evidence["prefix"])
        aliases = {observation["id"], observation["xml_id"]} - {None, ""}
        related = [
            r
            for r in refinements
            if (
                r["target_source_index"] == observation["source_index"]
                or (r["association"] == "ambiguous" and r["target_id"] in aliases)
            )
        ]
        if len(related) + len(result["declarations"]) > 256:
            raise ValueError("declaration_limit")
        for refinement in related:
            iri = _scheme(refinement["scheme"], prefixes)
            result["declarations"].append(
                {
                    "kind": "identifier_type",
                    "source_index": refinement["source_index"],
                    "value": refinement["value"],
                    "scheme": refinement["scheme"],
                    "scheme_iri": iri,
                    "refines": refinement["refines"],
                    "association": refinement["association"],
                }
            )
            if refinement["association"] == "ambiguous":
                issues.append("identifier_type_target_ambiguous")
            elif refinement["association"] != "identifier":
                issues.append("identifier_type_target_unresolved")
            elif not refinement["text_only"]:
                issues.append("identifier_type_not_text")
            elif evidence["package_version"] != "3.0":
                issues.append("unsupported_scheme_version")
            elif prefixes is None:
                issues.append("prefix_declaration_invalid")
            elif iri != ONIX + "codelist5":
                issues.append("unsupported_identifier_type_scheme")
            elif refinement["value"] not in {"02", "15"}:
                issues.append("unsupported_identifier_type_code")
            else:
                types.append(
                    (
                        10 if refinement["value"] == "02" else 13,
                        "onix_isbn10" if refinement["value"] == "02" else "onix_isbn13",
                    )
                )
        if len(related) > 1:
            issues.insert(0, "multiple_identifier_types")
        if "multiple_identifier_types" in issues or "identifier_type_target_ambiguous" in issues:
            result.update(status="ambiguous", reason_codes=list(dict.fromkeys(issues)))
            return result
    if urn and any(c in payload for c in "#?"):
        result["reason_codes"].append("urn_components_unassessed")
        return result
    if issues:
        result["status"] = "ambiguous" if urn_number or types else "unsupported"
        result["reason_codes"] += issues
        return result
    for length, basis in types:
        if length is not None and len(payload.replace("-", "")) != length:
            result.update(status="ambiguous" if urn_number else "invalid")
            result["reason_codes"].append("isbn_type_length_mismatch")
            return result
        number = canonical(payload)
        if number is None:
            result.update(status="invalid")
            result["reason_codes"].append("invalid_isbn")
            return result
        result["basis"] = basis
    if urn:
        number = urn_number
        result["basis"] = "urn" if number else None
    if number:
        result.update(status="unknown", canonical_isbn13=number)
    else:
        result["status"] = "invalid" if urn else "unsupported"
        result["reason_codes"].append("invalid_isbn" if urn else "isbn_not_declared")
    return result


def entries(values, evidence, complete, canonical):
    result = []
    declarations = 0
    for index, value in enumerate(values):
        observation = evidence["entries"][index] if evidence is not None else None
        entry = _entry(
            value, observation, evidence["refinements"] if evidence else [], evidence, canonical
        )
        declarations += len(entry["declarations"])
        if declarations > 256:
            raise ValueError("declaration_limit")
        if not complete:
            entry.update(status="unknown", canonical_isbn13=None, basis=None)
            entry["reason_codes"].append("inspection_incomplete")
        result.append(entry)
    return result
