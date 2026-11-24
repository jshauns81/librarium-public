"""Synthetic curated-reference stores for tests; never a real authority or reference corpus."""

import hashlib
import json
import os
from copy import deepcopy
from types import SimpleNamespace

AUTHORITY = "synthetic.authority"
REFERENCE = "synthetic.reference-1"
CLAIMS = ["work_identity", "complete_collection", "edition_identity", "language", "revision"]
ISSUED = "2026-01-01T00:00:00Z"
UNTIL = "2099-01-01T00:00:00Z"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put(directory, name, data):
    directory.mkdir(exist_ok=True)
    path = directory / name
    if path.exists():
        path.chmod(0o644)
    path.write_bytes(data)
    path.chmod(0o444)
    return path


def manifest(artifact, pin, work_id, evidence, *, scope="standalone_work"):
    constituents = (
        [{"work_id": work_id, "position": 1, "evidence_sha256": evidence["constituent"]}]
        if scope == "standalone_work"
        else [
            {"work_id": f"w_story_{index}", "position": index, "evidence_sha256": digest}
            for index, digest in enumerate(evidence["stories"], 1)
        ]
    )
    return {
        "schema": "librarium.complete-content-reference.v1",
        "reference_id": REFERENCE,
        "authority_id": AUTHORITY,
        "issued_at": ISSUED,
        "valid_until": UNTIL,
        "artifact": {"sha256": sha(artifact), "size": len(artifact), "format": "epub"},
        "publication": {
            "catalogue_version": pin["version"],
            "catalogue_sha256": pin["sha256"],
            "work_id": work_id,
            "edition_id": "e_fixture",
            "language": "en",
            "revision": "r1",
            "scope": scope,
        },
        "acquisition": {
            "method": "synthetic_fixture",
            "acquired_at": ISSUED,
            "source_lineage_id": "synthetic.lineage-1",
            "receipt_sha256": evidence["receipt"],
            "publication_evidence_sha256": evidence["publication"],
        },
        "coverage": {
            "protocol": "librarium.complete-reference-curation.v1",
            "record_sha256": evidence["coverage"],
            "expected_constituents": constituents,
            "unsupported_components": [],
        },
    }


def registry(manifest_sha256):
    return {
        "schema": "librarium.content-trust-registry.v1",
        "registry_id": "synthetic.registry",
        "revision": 1,
        "issued_at": ISSUED,
        "valid_until": UNTIL,
        "authorities": [
            {
                "authority_id": AUTHORITY,
                "method": "operator_curated_local_reference",
                "scope": list(CLAIMS),
                "valid_from": ISSUED,
                "valid_until": UNTIL,
                "revoked_at": None,
            }
        ],
        "references": [
            {
                "reference_id": REFERENCE,
                "authority_id": AUTHORITY,
                "manifest_sha256": manifest_sha256,
            }
        ],
        "revocations": [],
    }


def build(
    root,
    settings,
    artifact,
    pin,
    work_id="w_fixture",
    *,
    scope="standalone_work",
    edit_manifest=None,
    edit_registry=None,
    configure=True,
):
    """Write a complete synthetic store under root and select it through settings."""
    root.mkdir(exist_ok=True)
    evidence: dict = {}
    for name in ("receipt", "publication", "coverage", "constituent"):
        data = f"synthetic {name} evidence".encode()
        put(root / "evidence", sha(data), data)
        evidence[name] = sha(data)
    evidence["stories"] = []
    for index in (1, 2):
        data = f"synthetic story {index} evidence".encode()
        put(root / "evidence", sha(data), data)
        evidence["stories"].append(sha(data))
    put(root / "artifacts", sha(artifact), artifact)
    value = manifest(artifact, pin, work_id, evidence, scope=scope)
    if edit_manifest is not None:
        edit_manifest(value)
    manifest_bytes = json.dumps(value, indent=2).encode()
    put(root / "manifests", sha(manifest_bytes) + ".json", manifest_bytes)
    listed = registry(sha(manifest_bytes))
    if edit_registry is not None:
        edit_registry(listed)
    registry_bytes = json.dumps(listed, indent=2).encode()
    path = put(root, "registry.json", registry_bytes)
    if configure:
        settings.LIBRARIUM_CONTENT_TRUST_REGISTRY = str(path)
        settings.LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256 = sha(registry_bytes)
    return SimpleNamespace(
        root=root,
        path=path,
        artifact=artifact,
        evidence=evidence,
        manifest=deepcopy(value),
        manifest_sha256=sha(manifest_bytes),
        registry=deepcopy(listed),
        registry_sha256=sha(registry_bytes),
        pin={
            "reference_id": REFERENCE,
            "registry_sha256": sha(registry_bytes),
            "manifest_sha256": sha(manifest_bytes),
        },
    )


def raw_manifest(store, data: bytes):
    """Replace the selected manifest with exact bytes and re-pin the registry to them."""
    put(store.root / "manifests", sha(data) + ".json", data)
    listed = deepcopy(store.registry)
    listed["references"][0]["manifest_sha256"] = sha(data)
    registry_bytes = json.dumps(listed).encode()
    put(store.root, "registry.json", registry_bytes)
    store.registry = listed
    store.manifest_sha256 = sha(data)
    store.registry_sha256 = sha(registry_bytes)
    store.pin = {
        "reference_id": REFERENCE,
        "registry_sha256": store.registry_sha256,
        "manifest_sha256": store.manifest_sha256,
    }
    return store


def configure_raw_registry(store, settings, data: bytes):
    put(store.root, "registry.json", data)
    settings.LIBRARIUM_CONTENT_TRUST_REGISTRY = str(store.path)
    settings.LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256 = sha(data)
    store.registry_sha256 = sha(data)
    store.pin = {**store.pin, "registry_sha256": sha(data)}
    return store


def writable(path):
    os.chmod(path, 0o644)
