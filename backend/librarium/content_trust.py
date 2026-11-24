"""Operator-curated complete references: strict digest-store reads and exact-byte authentication.

The registry path and digest are operator configuration, never request fields. A request pin
only selects among independently configured records; it cannot nominate an authority, key,
path or URL. Positive authentication requires the exact preserved reference bytes.
"""

import hashlib
import json
import os
import re
import stat
import time
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings

from librarium import catalogue

DISCOVERY_POLICY = "librarium.content-trust-discovery.v1"
POLICY = "librarium.content-reference-authentication.v1"
REGISTRY_SCHEMA = "librarium.content-trust-registry.v1"
MANIFEST_SCHEMA = "librarium.complete-content-reference.v1"
CURATION_PROTOCOL = "librarium.complete-reference-curation.v1"
AUTHORITY_METHOD = "operator_curated_local_reference"
CLAIMS = ("work_identity", "complete_collection", "edition_identity", "language", "revision")
SCOPES = {"standalone_work", "complete_collection"}
FORMATS = {"epub"}
MAX_REGISTRY_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_EVIDENCE_BYTES = 4 * 1024 * 1024
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_AUTHORITIES = 64
MAX_REFERENCES = 1024
MAX_REVOCATIONS = 1024
MAX_CONSTITUENTS = 256
MAX_UNSUPPORTED = 64
MAX_DISCOVERED = 64
DISCOVERY_BYTES = 8 * 1024 * 1024
DISCOVERY_SECONDS = 5
CHUNK = 1024 * 1024
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}")
CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
LANGUAGE = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]{1,8}){0,4}")
PIN_FIELDS = {"reference_id", "registry_sha256", "manifest_sha256"}
OPEN_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
OPEN_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class TrustError(Exception):
    status = 400


class _Refused(Exception):
    def __init__(self, *codes):
        super().__init__(*codes)
        self.codes = codes


def _id(value):
    return isinstance(value, str) and bool(ID.fullmatch(value))


def _digest(value):
    return isinstance(value, str) and bool(catalogue.DIGEST.fullmatch(value))


def validate_pin(value):
    if (
        not isinstance(value, dict)
        or set(value) != PIN_FIELDS
        or not _id(value["reference_id"])
        or not _digest(value["registry_sha256"])
        or not _digest(value["manifest_sha256"])
    ):
        raise TrustError("Choose an exact advertised reference, registry and manifest pin")


def configured():
    return bool(
        getattr(settings, "LIBRARIUM_CONTENT_TRUST_REGISTRY", "")
        and getattr(settings, "LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256", "")
    )


# Store reads


def _overlaps(root):
    for option in (
        "LIBRARIUM_ARTIFACT_DIR",
        "DIRECT_LIBRARY_ROOT",
        "LIBRARIUM_REFERENCE_STATE_DIR",
    ):
        other = getattr(settings, option, "")
        if other:
            other = Path(os.path.realpath(other))
            if root.is_relative_to(other) or other.is_relative_to(root):
                return True
    return False


def _open_root(path):
    root = Path(os.path.realpath(path.parent))
    if _overlaps(root):
        raise _Refused("trust_store_overlaps_writable_location")
    try:
        return os.open(path.parent, OPEN_DIRECTORY)
    except OSError:
        raise _Refused("registry_unavailable") from None


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read(directory, name, limit, *, missing, oversize, checkpoint, keep=True):
    """Read one no-follow, read-only regular file; returns (bytes|None, sha256, signature)."""
    try:
        descriptor = os.open(name, OPEN_FILE, dir_fd=directory)
    except OSError:
        raise _Refused(missing) from None
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise _Refused(missing)
        if stat.S_IMODE(before.st_mode) & 0o222 and not (
            os.fstatvfs(descriptor).f_flag & os.ST_RDONLY
        ):
            raise _Refused("trust_file_writable")
        if not 1 <= before.st_size <= limit:
            raise _Refused(oversize)
        digest = hashlib.sha256()
        chunks = []
        observed = 0
        while True:
            checkpoint(0)
            chunk = os.read(descriptor, min(CHUNK, limit + 1 - observed))
            if not chunk:
                break
            observed += len(chunk)
            checkpoint(len(chunk))
            if observed > before.st_size:
                raise _Refused("trust_store_changed")
            digest.update(chunk)
            if keep:
                chunks.append(chunk)
        if observed != before.st_size or _signature(os.fstat(descriptor)) != _signature(before):
            raise _Refused("trust_store_changed")
        return (b"".join(chunks) if keep else None), digest.hexdigest(), _signature(before)
    except OSError:
        raise _Refused(missing) from None
    finally:
        os.close(descriptor)


def _subdirectory(root, name, missing):
    try:
        return os.open(name, OPEN_DIRECTORY, dir_fd=root)
    except OSError:
        raise _Refused(missing) from None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject(_value):
    raise ValueError("unsupported JSON number")


def _json(data, code):
    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_unique,
            parse_float=_reject,
            parse_constant=_reject,
        )
    except ValueError, RecursionError:
        raise _Refused(code) from None


# Strict schemas


def _require(condition):
    if not condition:
        raise ValueError


def _fields(value, names):
    _require(isinstance(value, dict) and set(value) == names)
    return value


def _time(value, *, nullable=False):
    if value is None and nullable:
        return None
    _require(isinstance(value, str) and 1 <= len(value) <= 40 and "T" in value)
    parsed = datetime.fromisoformat(value)
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None)
    return parsed


def _integer(value, low, high):
    _require(type(value) is int and low <= value <= high)
    return value


def _list(value, limit):
    _require(isinstance(value, list) and len(value) <= limit)
    return value


def _interval(start, end):
    _require(end is None or end > start)


def _registry(value):
    _fields(
        value,
        {
            "schema",
            "registry_id",
            "revision",
            "issued_at",
            "valid_until",
            "authorities",
            "references",
            "revocations",
        },
    )
    _require(value["schema"] == REGISTRY_SCHEMA and _id(value["registry_id"]))
    _integer(value["revision"], 1, 2**31 - 1)
    issued = _time(value["issued_at"])
    until = _time(value["valid_until"], nullable=True)
    _interval(issued, until)
    authorities = {}
    for entry in _list(value["authorities"], MAX_AUTHORITIES):
        _fields(
            entry, {"authority_id", "method", "scope", "valid_from", "valid_until", "revoked_at"}
        )
        scope = _list(entry["scope"], len(CLAIMS))
        _require(
            _id(entry["authority_id"])
            and entry["authority_id"] not in authorities
            and entry["method"] == AUTHORITY_METHOD
            and scope
            and len(set(scope)) == len(scope)
            and all(isinstance(claim, str) and claim in CLAIMS for claim in scope)
        )
        start = _time(entry["valid_from"])
        end = _time(entry["valid_until"], nullable=True)
        _interval(start, end)
        authorities[entry["authority_id"]] = {
            "scope": set(scope),
            "valid_from": start,
            "valid_until": end,
            "revoked_at": _time(entry["revoked_at"], nullable=True),
        }
    _require(authorities)
    references = {}
    for entry in _list(value["references"], MAX_REFERENCES):
        _fields(entry, {"reference_id", "authority_id", "manifest_sha256"})
        _require(
            _id(entry["reference_id"])
            and entry["reference_id"] not in references
            and entry["authority_id"] in authorities
            and _digest(entry["manifest_sha256"])
        )
        references[entry["reference_id"]] = entry
    revocations = {}
    for entry in _list(value["revocations"], MAX_REVOCATIONS):
        _fields(entry, {"reference_id", "revoked_at", "reason_code"})
        _require(
            _id(entry["reference_id"])
            and entry["reference_id"] not in revocations
            and isinstance(entry["reason_code"], str)
            and CODE.fullmatch(entry["reason_code"])
        )
        revocations[entry["reference_id"]] = _time(entry["revoked_at"])
    return {
        "issued_at": issued,
        "valid_until": until,
        "authorities": authorities,
        "references": references,
        "revocations": revocations,
    }


def _manifest(value):
    _fields(
        value,
        {
            "schema",
            "reference_id",
            "authority_id",
            "issued_at",
            "valid_until",
            "artifact",
            "publication",
            "acquisition",
            "coverage",
        },
    )
    _require(
        value["schema"] == MANIFEST_SCHEMA
        and _id(value["reference_id"])
        and _id(value["authority_id"])
    )
    issued = _time(value["issued_at"])
    _interval(issued, _time(value["valid_until"], nullable=True))
    artifact = _fields(value["artifact"], {"sha256", "size", "format"})
    _require(_digest(artifact["sha256"]) and artifact["format"] in FORMATS)
    _integer(artifact["size"], 1, MAX_ARTIFACT_BYTES)
    publication = _fields(
        value["publication"],
        {
            "catalogue_version",
            "catalogue_sha256",
            "work_id",
            "edition_id",
            "language",
            "revision",
            "scope",
        },
    )
    _require(
        isinstance(publication["catalogue_version"], str)
        and catalogue.valid_version(publication["catalogue_version"])
        and _digest(publication["catalogue_sha256"])
        and _id(publication["work_id"])
        and (publication["edition_id"] is None or _id(publication["edition_id"]))
        and (publication["revision"] is None or _id(publication["revision"]))
        and (
            publication["language"] is None
            or (
                isinstance(publication["language"], str)
                and len(publication["language"]) <= 35
                and LANGUAGE.fullmatch(publication["language"])
            )
        )
        and publication["scope"] in SCOPES
    )
    acquisition = _fields(
        value["acquisition"],
        {
            "method",
            "acquired_at",
            "source_lineage_id",
            "receipt_sha256",
            "publication_evidence_sha256",
        },
    )
    _require(
        isinstance(acquisition["method"], str)
        and CODE.fullmatch(acquisition["method"])
        and _id(acquisition["source_lineage_id"])
        and _digest(acquisition["receipt_sha256"])
        and _digest(acquisition["publication_evidence_sha256"])
        and _time(acquisition["acquired_at"]) <= issued
    )
    coverage = _fields(
        value["coverage"],
        {"protocol", "record_sha256", "expected_constituents", "unsupported_components"},
    )
    _require(
        isinstance(coverage["protocol"], str)
        and len(coverage["protocol"]) <= 80
        and _digest(coverage["record_sha256"])
    )
    for entry in _list(coverage["expected_constituents"], MAX_CONSTITUENTS):
        _fields(entry, {"work_id", "position", "evidence_sha256"})
        _require(_id(entry["work_id"]) and _digest(entry["evidence_sha256"]))
        _integer(entry["position"], 1, MAX_CONSTITUENTS)
    components = _list(coverage["unsupported_components"], MAX_UNSUPPORTED)
    _require(
        len(set(components)) == len(components)
        and all(isinstance(item, str) and CODE.fullmatch(item) for item in components)
    )
    return value


def _parse(schema, data, code):
    value = _json(data, code)
    try:
        return schema(value)
    except ValueError, TypeError, KeyError:
        raise _Refused(code) from None


def _coverage_reasons(manifest):
    publication, coverage = manifest["publication"], manifest["coverage"]
    reasons = []
    if coverage["protocol"] != CURATION_PROTOCOL:
        reasons.append("coverage_protocol_unsupported")
    if coverage["unsupported_components"]:
        reasons.append("coverage_unsupported_components")
    items = coverage["expected_constituents"]
    works = [item["work_id"] for item in items]
    complete = sorted(item["position"] for item in items) == list(range(1, len(items) + 1)) and (
        len(set(works)) == len(works)
    )
    if publication["scope"] == "standalone_work":
        complete &= works == [publication["work_id"]]
    else:
        # One story cannot identify a collection, and the container is not its own story.
        complete &= len(works) >= 2 and publication["work_id"] not in works
    if not complete:
        reasons.append("coverage_incomplete")
    return reasons


def _required_claims(manifest):
    return {"work_identity"} | (
        {"complete_collection"}
        if manifest["publication"]["scope"] == "complete_collection"
        else set()
    )


def _claims(manifest, scope, *, edition_current=True):
    publication = manifest["publication"]
    claims = _required_claims(manifest)
    if publication["edition_id"] is not None and edition_current:
        claims.add("edition_identity")
    if publication["language"] is not None:
        claims.add("language")
    if publication["revision"] is not None:
        claims.add("revision")
    return [claim for claim in CLAIMS if claim in claims and claim in scope]


def _temporal_reasons(registry, entry, manifest, revocation, now):
    authority = registry["authorities"][entry["authority_id"]]
    reasons = []
    if registry["issued_at"] > now:
        reasons.append("registry_not_yet_valid")
    if registry["valid_until"] is not None and registry["valid_until"] <= now:
        reasons.append("registry_expired")
    if authority["valid_from"] > now:
        reasons.append("authority_not_yet_valid")
    if authority["valid_until"] is not None and authority["valid_until"] <= now:
        reasons.append("authority_expired")
    if authority["revoked_at"] is not None and authority["revoked_at"] <= now:
        reasons.append("authority_revoked")
    if revocation is not None and revocation <= now:
        reasons.append("reference_revoked")
    if manifest is not None:
        issued = _time(manifest["issued_at"])
        until = _time(manifest["valid_until"], nullable=True)
        if issued > now:
            reasons.append("reference_not_yet_valid")
        if until is not None and until <= now:
            reasons.append("reference_expired")
        if issued < authority["valid_from"] or (
            authority["valid_until"] is not None and issued >= authority["valid_until"]
        ):
            reasons.append("reference_outside_authority_validity")
        if not _required_claims(manifest) <= authority["scope"]:
            reasons.append("authority_scope_insufficient")
    return reasons


class _Store:
    """One configured registry, verified against its independently configured digest."""

    def __init__(self, checkpoint):
        path = Path(settings.LIBRARIUM_CONTENT_TRUST_REGISTRY)
        self.name = path.name
        self.checkpoint = checkpoint
        self.root = _open_root(path)
        self.directories = {}
        try:
            data, digest, self.signature = _read(
                self.root,
                self.name,
                MAX_REGISTRY_BYTES,
                missing="registry_unavailable",
                oversize="registry_invalid",
                checkpoint=checkpoint,
            )
            if digest != settings.LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256:
                raise _Refused("registry_digest_mismatch")
            self.registry = _parse(_registry, data, "registry_invalid")
        except BaseException:
            self.close()
            raise

    def close(self):
        for descriptor in self.directories.values():
            os.close(descriptor)
        os.close(self.root)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _directory(self, name, missing):
        if name not in self.directories:
            self.directories[name] = _subdirectory(self.root, name, missing)
        return self.directories[name]

    def manifest(self, digest):
        data, observed, _ = _read(
            self._directory("manifests", "manifest_unavailable"),
            digest + ".json",
            MAX_MANIFEST_BYTES,
            missing="manifest_unavailable",
            oversize="manifest_invalid",
            checkpoint=self.checkpoint,
        )
        if observed != digest:
            raise _Refused("manifest_digest_mismatch")
        return _parse(_manifest, data, "manifest_invalid")

    def evidence(self, digest):
        _, observed, _ = _read(
            self._directory("evidence", "evidence_unavailable"),
            digest,
            MAX_EVIDENCE_BYTES,
            missing="evidence_unavailable",
            oversize="evidence_unavailable",
            checkpoint=self.checkpoint,
            keep=False,
        )
        if observed != digest:
            raise _Refused("evidence_digest_mismatch")

    def artifact(self, artifact):
        _, observed, signature = _read(
            self._directory("artifacts", "reference_artifact_unavailable"),
            artifact["sha256"],
            MAX_ARTIFACT_BYTES,
            missing="reference_artifact_unavailable",
            oversize="reference_artifact_mismatch",
            checkpoint=self.checkpoint,
            keep=False,
        )
        if observed != artifact["sha256"] or signature[2] != artifact["size"]:
            raise _Refused("reference_artifact_mismatch")

    def fence(self):
        """Refuse a result if the configured registry file changed during the check."""
        try:
            descriptor = os.open(self.name, OPEN_FILE, dir_fd=self.root)
        except OSError:
            raise _Refused("trust_store_changed") from None
        try:
            if _signature(os.fstat(descriptor)) != self.signature:
                raise _Refused("trust_store_changed")
        finally:
            os.close(descriptor)


def _verify_artifact(store, artifact):
    store.artifact(artifact)


def _no_checkpoint(_count):
    return None


# Discovery


def discover(version, sha256, work_id):
    result = {
        "policy_version": DISCOVERY_POLICY,
        "status": "not_configured",
        "catalogue": {"version": version, "sha256": sha256, "work_id": work_id},
        "registry_sha256": None,
        "references": [],
        "reason_codes": ["trust_not_configured"],
    }
    if not configured():
        return result
    deadline = time.monotonic() + DISCOVERY_SECONDS
    spent = 0

    def budget(count):
        nonlocal spent
        spent += count
        if spent > DISCOVERY_BYTES or time.monotonic() > deadline:
            raise _Refused("discovery_budget_exceeded")

    now = datetime.now(UTC)
    references: list[dict] = []
    excluded = truncated = False
    try:
        with _Store(budget) as store:
            registry = store.registry
            if registry["issued_at"] > now:
                raise _Refused("registry_not_yet_valid")
            if registry["valid_until"] is not None and registry["valid_until"] <= now:
                raise _Refused("registry_expired")
            for reference_id, entry in sorted(registry["references"].items()):
                try:
                    manifest = store.manifest(entry["manifest_sha256"])
                except _Refused as refused:
                    if refused.codes == ("discovery_budget_exceeded",):
                        raise
                    excluded = True
                    continue
                if (
                    manifest["reference_id"] != reference_id
                    or manifest["authority_id"] != entry["authority_id"]
                ):
                    excluded = True
                    continue
                if manifest["publication"]["work_id"] != work_id:
                    continue
                authority = registry["authorities"][entry["authority_id"]]
                if _temporal_reasons(
                    registry, entry, manifest, registry["revocations"].get(reference_id), now
                ) or _coverage_reasons(manifest):
                    excluded = True
                    continue
                if len(references) >= MAX_DISCOVERED:
                    truncated = True
                    break
                publication = manifest["publication"]
                references.append(
                    {
                        "reference_id": reference_id,
                        "manifest_sha256": entry["manifest_sha256"],
                        "authority_id": entry["authority_id"],
                        "artifact": dict(manifest["artifact"]),
                        "publication": {
                            key: publication[key]
                            for key in ("work_id", "edition_id", "language", "revision", "scope")
                        },
                        "claims": _claims(manifest, authority["scope"]),
                    }
                )
            store.fence()
    except _Refused as refused:
        return {**result, "status": "unavailable", "reason_codes": [refused.codes[0]]}
    codes = []
    if excluded:
        codes.append("references_excluded")
    if truncated:
        codes.append("references_truncated")
    if not references and not excluded:
        codes.append("no_matching_references")
    return {
        **result,
        "status": "available",
        "registry_sha256": settings.LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256,
        "references": references,
        "reason_codes": codes,
    }


# Authentication


def authenticate(
    pin,
    *,
    source_sha256,
    source_size,
    report_sha256,
    catalogue,
    checked_at,
    resolver=None,
    checkpoint=None,
):
    """Return a source-bound historical authentication observation for one explicit pin.

    No pin means no trust configuration is consulted. Exceptions raised by ``checkpoint``
    (cancellation or budget) propagate to the caller unchanged.
    """
    checkpoint = checkpoint or _no_checkpoint
    result = {
        "schema_version": POLICY,
        "status": "not_requested",
        "reason_codes": ["reference_not_pinned"],
        "source_sha256": source_sha256,
        "report_sha256": report_sha256,
        "catalogue": dict(catalogue),
        "reference_id": None,
        "reference_sha256": None,
        "manifest_sha256": None,
        "registry_sha256": None,
        "authority_id": None,
        "checked_at": checked_at.isoformat(),
        "claims": [],
        "observation": "historical",
        "reference_publication": None,
    }
    if pin is None:
        return result
    validate_pin(pin)
    result.update(
        status="unconfirmed",
        reference_id=pin["reference_id"],
        manifest_sha256=pin["manifest_sha256"],
        registry_sha256=pin["registry_sha256"],
    )
    if not configured():
        return {**result, "reason_codes": ["trust_not_configured"]}
    if pin["registry_sha256"] != settings.LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256:
        return {**result, "reason_codes": ["registry_pin_mismatch"]}
    checkpoint(0)
    try:
        with _Store(checkpoint) as store:
            registry = store.registry
            entry = registry["references"].get(pin["reference_id"])
            if entry is None:
                raise _Refused("reference_not_registered")
            result["authority_id"] = entry["authority_id"]
            if entry["manifest_sha256"] != pin["manifest_sha256"]:
                raise _Refused("manifest_pin_mismatch")
            manifest = store.manifest(pin["manifest_sha256"])
            if (
                manifest["reference_id"] != pin["reference_id"]
                or manifest["authority_id"] != entry["authority_id"]
            ):
                raise _Refused("manifest_identity_mismatch")
            publication = manifest["publication"]
            result["reference_sha256"] = manifest["artifact"]["sha256"]
            result["reference_publication"] = dict(publication)
            reasons = _temporal_reasons(
                registry,
                entry,
                manifest,
                registry["revocations"].get(pin["reference_id"]),
                checked_at,
            )
            # The reference's catalogue pin is acquisition provenance; the current assessment
            # pin must still resolve the same exact work ID, with no title or alias remapping.
            if publication["work_id"] != catalogue["work_id"]:
                reasons.append("work_mismatch")
            elif resolver is None or not resolver.work_current(publication["work_id"]):
                reasons.append("reference_work_not_current")
            coverage = _coverage_reasons(manifest)
            reasons += coverage
            if (
                not coverage
                and publication["scope"] == "complete_collection"
                and (
                    resolver is None
                    or not all(
                        resolver.work_current(item["work_id"])
                        for item in manifest["coverage"]["expected_constituents"]
                    )
                )
            ):
                reasons.append("constituent_work_not_current")
            if reasons:
                raise _Refused(*reasons)
            acquisition = manifest["acquisition"]
            for digest in dict.fromkeys(
                [
                    acquisition["receipt_sha256"],
                    acquisition["publication_evidence_sha256"],
                    manifest["coverage"]["record_sha256"],
                    *(
                        item["evidence_sha256"]
                        for item in manifest["coverage"]["expected_constituents"]
                    ),
                ]
            ):
                store.evidence(digest)
            _verify_artifact(store, manifest["artifact"])
            store.fence()
            scope = registry["authorities"][entry["authority_id"]]["scope"]
    except _Refused as refused:
        return {**result, "reason_codes": sorted(set(refused.codes))}
    artifact = manifest["artifact"]
    if source_sha256 != artifact["sha256"] or source_size != artifact["size"]:
        return {**result, "status": "different_bytes", "reason_codes": ["reference_bytes_differ"]}
    edition = publication["edition_id"]
    edition_current = edition is not None and resolver.edition_work(edition) == catalogue["work_id"]
    return {
        **result,
        "status": "authenticated_reference_match",
        "reason_codes": ["reference_edition_not_current"]
        if edition is not None and not edition_current
        else [],
        "claims": _claims(manifest, scope, edition_current=edition_current),
    }
