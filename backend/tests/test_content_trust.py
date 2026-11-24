"""Curated reference trust: strict store reads, metadata discovery and exact-byte authentication."""

import json
import os
from datetime import UTC, datetime

import pytest
import trust_store
from librarium import content_trust

PIN = {"version": "2026.10.01.1", "sha256": "c" * 64}
WORK = "w_fixture"
ARTIFACT = b"synthetic complete reference epub bytes"
NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)


@pytest.fixture
def unconfigured(settings):
    settings.LIBRARIUM_CONTENT_TRUST_REGISTRY = ""
    settings.LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256 = ""
    return settings


@pytest.fixture
def store(tmp_path, unconfigured):
    return trust_store.build(tmp_path / "trust", unconfigured, ARTIFACT, PIN, WORK)


def make(tmp_path, settings, **kwargs):
    return trust_store.build(tmp_path / "trust", settings, ARTIFACT, PIN, WORK, **kwargs)


class Resolver:
    """The current pinned catalogue as seen by an assessment: exact IDs, no remapping."""

    def __init__(self, works=(WORK, "w_story_1", "w_story_2"), editions=None):
        self.works = set(works)
        self.editions = {"e_fixture": WORK} if editions is None else editions

    def work_current(self, work_id):
        return work_id in self.works

    def edition_work(self, edition_id):
        return self.editions.get(edition_id)


def authenticate(
    store_or_pin, *, source=ARTIFACT, catalogue=None, when=NOW, resolver=None, **kwargs
):
    pin = getattr(store_or_pin, "pin", store_or_pin)
    return content_trust.authenticate(
        pin,
        source_sha256=trust_store.sha(source),
        source_size=len(source),
        report_sha256="d" * 64,
        catalogue=catalogue or {**PIN, "work_id": WORK},
        checked_at=when,
        resolver=resolver or Resolver(),
        **kwargs,
    )


def discover(version=PIN["version"], sha256=PIN["sha256"], work=WORK):
    return content_trust.discover(version, sha256, work)


# Discovery


def test_unconfigured_discovery_is_a_usable_unknown(unconfigured):
    result = discover()
    assert result == {
        "policy_version": "librarium.content-trust-discovery.v1",
        "status": "not_configured",
        "catalogue": {**PIN, "work_id": WORK},
        "registry_sha256": None,
        "references": [],
        "reason_codes": ["trust_not_configured"],
    }


def test_discovery_lists_metadata_without_private_evidence_or_locators(store):
    os.chmod(store.root / "artifacts", 0o000)
    try:
        result = discover()
    finally:
        os.chmod(store.root / "artifacts", 0o755)
    assert result["status"] == "available"
    assert result["registry_sha256"] == store.registry_sha256
    assert result["reason_codes"] == []
    assert result["references"] == [
        {
            "reference_id": trust_store.REFERENCE,
            "manifest_sha256": store.manifest_sha256,
            "authority_id": trust_store.AUTHORITY,
            "artifact": {
                "sha256": trust_store.sha(ARTIFACT),
                "size": len(ARTIFACT),
                "format": "epub",
            },
            "publication": {
                "work_id": WORK,
                "edition_id": "e_fixture",
                "language": "en",
                "revision": "r1",
                "scope": "standalone_work",
            },
            "claims": ["work_identity", "edition_identity", "language", "revision"],
        }
    ]
    text = json.dumps(result)
    for private in (str(store.root), "receipt", "acquisition", "lineage", "evidence", "label"):
        assert private not in text


def test_discovery_never_offers_another_work(store):
    result = discover(work="w_other")
    assert result["status"] == "available" and result["references"] == []
    assert result["reason_codes"] == ["no_matching_references"]


def test_discovery_keeps_same_work_after_routine_catalogue_refresh(store):
    result = discover(version="2026.10.02.1", sha256="e" * 64)
    assert result["catalogue"] == {"version": "2026.10.02.1", "sha256": "e" * 64, "work_id": WORK}
    assert [ref["reference_id"] for ref in result["references"]] == [trust_store.REFERENCE]


def test_discovery_excludes_revoked_and_partial_references_with_a_reason(tmp_path, unconfigured):
    def revoke(value):
        value["revocations"] = [
            {
                "reference_id": trust_store.REFERENCE,
                "revoked_at": "2026-02-01T00:00:00Z",
                "reason_code": "curation_withdrawn",
            }
        ]

    make(tmp_path, unconfigured, edit_registry=revoke)
    result = discover()
    assert result["references"] == []
    assert result["reason_codes"] == ["references_excluded"]


@pytest.mark.parametrize(
    "corrupt, reason",
    [
        ("digest", "registry_digest_mismatch"),
        ("symlink", "registry_unavailable"),
        ("missing", "registry_unavailable"),
        ("duplicate_key", "registry_invalid"),
        ("unknown_field", "registry_invalid"),
        ("float_revision", "registry_invalid"),
        ("naive_time", "registry_invalid"),
        ("uppercase_digest", "registry_invalid"),
        ("unknown_authority", "registry_invalid"),
        ("duplicate_reference", "registry_invalid"),
        ("oversize", "registry_invalid"),
        ("writable", "trust_file_writable"),
        ("expired", "registry_expired"),
    ],
)
def test_corrupt_configured_store_is_unavailable_without_leaking_paths(
    tmp_path, unconfigured, corrupt, reason
):
    store = make(tmp_path, unconfigured)
    listed = json.loads(json.dumps(store.registry))
    text = None
    if corrupt == "digest":
        unconfigured.LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256 = "f" * 64
    elif corrupt == "symlink":
        target = store.root / "registry-target.json"
        os.rename(store.path, target)
        os.symlink(target.name, store.path)
    elif corrupt == "missing":
        store.path.unlink()
    elif corrupt == "duplicate_key":
        text = json.dumps(listed)[:-1] + ', "revision": 2}'
    elif corrupt == "unknown_field":
        listed["public_key"] = "self-supplied"
    elif corrupt == "float_revision":
        listed["revision"] = 1.0
    elif corrupt == "naive_time":
        listed["issued_at"] = "2026-01-01T00:00:00"
    elif corrupt == "uppercase_digest":
        listed["references"][0]["manifest_sha256"] = store.manifest_sha256.upper()
    elif corrupt == "unknown_authority":
        listed["references"][0]["authority_id"] = "forged.authority"
    elif corrupt == "duplicate_reference":
        listed["references"].append(dict(listed["references"][0]))
    elif corrupt == "oversize":
        text = json.dumps(listed) + " " * content_trust.MAX_REGISTRY_BYTES
    elif corrupt == "writable":
        trust_store.writable(store.path)
    elif corrupt == "expired":
        listed["valid_until"] = "2026-02-01T00:00:00Z"
    if corrupt in {
        "duplicate_key",
        "unknown_field",
        "float_revision",
        "naive_time",
        "uppercase_digest",
        "unknown_authority",
        "duplicate_reference",
        "oversize",
        "expired",
    }:
        trust_store.configure_raw_registry(
            store, unconfigured, (text or json.dumps(listed)).encode()
        )
    result = discover()
    assert result["status"] == "unavailable"
    assert result["references"] == []
    assert result["reason_codes"] == [reason]
    assert str(tmp_path) not in json.dumps(result)


@pytest.mark.parametrize("location", ["artifact", "library", "inside_artifact"])
def test_store_overlapping_writable_locations_is_unavailable(tmp_path, unconfigured, location):
    store = make(tmp_path, unconfigured)
    if location == "artifact":
        unconfigured.LIBRARIUM_ARTIFACT_DIR = str(store.root / "artifacts")
    elif location == "library":
        unconfigured.DIRECT_LIBRARY_ROOT = str(tmp_path)
    else:
        unconfigured.LIBRARIUM_ARTIFACT_DIR = str(store.root)
    result = discover()
    assert result["status"] == "unavailable"
    assert result["reason_codes"] == ["trust_store_overlaps_writable_location"]


def test_discovery_api_is_strict_and_metadata_only(store, client):
    path = "/api/content-trust/references"
    query = {"version": PIN["version"], "sha256": PIN["sha256"], "work": WORK}
    reply = client.get(path, query)
    assert reply.status_code == 200
    assert reply["Cache-Control"] == "no-store"
    assert reply.json()["references"][0]["reference_id"] == trust_store.REFERENCE
    for bad in (
        {},
        {k: v for k, v in query.items() if k != "work"},
        {**query, "page": "1"},
        {**query, "sha256": "A" * 64},
        {**query, "version": "latest"},
        {**query, "work": ""},
        {**query, "work": "w" * 81},
    ):
        assert client.get(path, bad).status_code == 400
    assert (
        client.get(
            path + "?" + "&".join(f"{k}={v}" for k, v in query.items()) + "&work=x"
        ).status_code
        == 400
    )
    assert client.post(path, query).status_code == 405


# Authentication


def test_not_requested_never_reads_trust_configuration(store, monkeypatch):
    monkeypatch.setattr(content_trust, "_open_root", lambda *_: pytest.fail("config read"))
    result = authenticate(None)
    assert result["status"] == "not_requested"
    assert result["reason_codes"] == ["reference_not_pinned"]
    assert result["registry_sha256"] is None and result["reference_id"] is None
    assert result["claims"] == []
    assert result["observation"] == "historical"
    assert result["schema_version"] == "librarium.content-reference-authentication.v1"


def test_exact_curated_bytes_authenticate_only_supported_claims(store):
    result = authenticate(store)
    assert result == {
        "schema_version": "librarium.content-reference-authentication.v1",
        "status": "authenticated_reference_match",
        "reason_codes": [],
        "source_sha256": trust_store.sha(ARTIFACT),
        "report_sha256": "d" * 64,
        "catalogue": {**PIN, "work_id": WORK},
        "reference_id": trust_store.REFERENCE,
        "reference_sha256": trust_store.sha(ARTIFACT),
        "manifest_sha256": store.manifest_sha256,
        "registry_sha256": store.registry_sha256,
        "authority_id": trust_store.AUTHORITY,
        "checked_at": NOW.isoformat(),
        "claims": ["work_identity", "edition_identity", "language", "revision"],
        "observation": "historical",
        "reference_publication": {
            "catalogue_version": PIN["version"],
            "catalogue_sha256": PIN["sha256"],
            "work_id": WORK,
            "edition_id": "e_fixture",
            "language": "en",
            "revision": "r1",
            "scope": "standalone_work",
        },
    }


def test_refreshed_catalogue_with_same_work_id_still_authenticates(store):
    current = {"version": "2026.11.01.1", "sha256": "e" * 64, "work_id": WORK}
    result = authenticate(store, catalogue=current)
    assert result["status"] == "authenticated_reference_match"
    assert result["catalogue"] == current
    assert result["reference_publication"]["catalogue_version"] == PIN["version"]


def test_merged_or_unknown_current_work_refuses_without_remapping(store):
    result = authenticate(store, resolver=Resolver(works={"w_merged_target"}))
    assert result["status"] == "unconfirmed"
    assert result["reason_codes"] == ["reference_work_not_current"]
    assert result["claims"] == []


def test_edition_moved_under_another_work_supports_no_edition_claim(store):
    result = authenticate(store, resolver=Resolver(editions={"e_fixture": "w_other"}))
    assert result["status"] == "authenticated_reference_match"
    assert "edition_identity" not in result["claims"]
    assert result["reason_codes"] == ["reference_edition_not_current"]


def test_collection_constituent_missing_from_current_catalogue_refuses(tmp_path, unconfigured):
    store = make(tmp_path, unconfigured, scope="complete_collection")
    result = authenticate(store, resolver=Resolver(works={WORK, "w_story_1"}))
    assert result["status"] == "unconfirmed"
    assert result["reason_codes"] == ["constituent_work_not_current"]


def test_different_bytes_are_not_narrative_exclusion(store):
    result = authenticate(store, source=ARTIFACT + b"x")
    assert result["status"] == "different_bytes"
    assert result["claims"] == []
    assert result["reason_codes"] == ["reference_bytes_differ"]


def test_unconfigured_requested_reference_is_unconfirmed_not_false(unconfigured):
    result = authenticate(
        {
            "reference_id": trust_store.REFERENCE,
            "registry_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
        }
    )
    assert result["status"] == "unconfirmed"
    assert result["reason_codes"] == ["trust_not_configured"]
    assert result["reference_id"] == trust_store.REFERENCE
    assert result["registry_sha256"] == "a" * 64


def _revoke_reference(value):
    value["revocations"] = [
        {
            "reference_id": trust_store.REFERENCE,
            "revoked_at": "2026-02-01T00:00:00Z",
            "reason_code": "curation_withdrawn",
        }
    ]


def _revoke_authority(value):
    value["authorities"][0]["revoked_at"] = "2026-02-01T00:00:00Z"


def _expire_authority(value):
    value["authorities"][0]["valid_until"] = "2026-02-01T00:00:00Z"


def _narrow_scope(value):
    value["authorities"][0]["scope"] = ["language"]


def _expire_reference(value):
    value["valid_until"] = "2026-02-01T00:00:00Z"


def _future_reference(value):
    value["issued_at"] = "2027-01-01T00:00:00Z"


def _other_work(value):
    value["publication"]["work_id"] = "w_other"
    value["coverage"]["expected_constituents"][0]["work_id"] = "w_other"


def _self_keyed(value):
    value["authority_id"] = "self.nominated"


def _unsupported(value):
    value["coverage"]["unsupported_components"] = ["audio_media"]


def _missing_constituent(value):
    value["coverage"]["expected_constituents"] = []


def _wrong_constituent(value):
    value["coverage"]["expected_constituents"][0]["work_id"] = "w_contained_story"


def _missing_evidence(value):
    value["acquisition"]["receipt_sha256"] = "0" * 64


@pytest.mark.parametrize(
    "edit_registry, edit_manifest, reason",
    [
        (_revoke_reference, None, "reference_revoked"),
        (_revoke_authority, None, "authority_revoked"),
        (_expire_authority, None, "authority_expired"),
        (_narrow_scope, None, "authority_scope_insufficient"),
        (None, _expire_reference, "reference_expired"),
        (None, _future_reference, "reference_not_yet_valid"),
        (None, _other_work, "work_mismatch"),
        (None, _self_keyed, "manifest_identity_mismatch"),
        (None, _unsupported, "coverage_unsupported_components"),
        (None, _missing_constituent, "coverage_incomplete"),
        (None, _wrong_constituent, "coverage_incomplete"),
        (None, _missing_evidence, "evidence_unavailable"),
    ],
)
def test_invalid_curation_cannot_authenticate_exact_bytes(
    tmp_path, unconfigured, edit_registry, edit_manifest, reason
):
    store = make(tmp_path, unconfigured, edit_registry=edit_registry, edit_manifest=edit_manifest)
    result = authenticate(store)
    assert result["status"] == "unconfirmed"
    assert reason in result["reason_codes"]
    assert result["claims"] == []
    assert result["reference_id"] == trust_store.REFERENCE


def test_collection_requires_its_complete_constituent_set(tmp_path, unconfigured):
    store = make(tmp_path, unconfigured, scope="complete_collection")
    assert authenticate(store)["claims"] == [
        "work_identity",
        "complete_collection",
        "edition_identity",
        "language",
        "revision",
    ]

    def one_story(value):
        value["coverage"]["expected_constituents"] = value["coverage"]["expected_constituents"][:1]

    def duplicate_position(value):
        value["coverage"]["expected_constituents"][1]["position"] = 1

    def container_as_story(value):
        value["coverage"]["expected_constituents"][1]["work_id"] = WORK

    for edit in (one_story, duplicate_position, container_as_story):
        partial = make(tmp_path, unconfigured, scope="complete_collection", edit_manifest=edit)
        result = authenticate(partial)
        assert result["status"] == "unconfirmed"
        assert result["reason_codes"] == ["coverage_incomplete"]


def test_unknown_edition_language_and_revision_support_no_specific_claims(tmp_path, unconfigured):
    def unknown(value):
        value["publication"].update(edition_id=None, language=None, revision=None)

    result = authenticate(make(tmp_path, unconfigured, edit_manifest=unknown))
    assert result["status"] == "authenticated_reference_match"
    assert result["claims"] == ["work_identity"]


@pytest.mark.parametrize(
    "pin_change, reason",
    [
        ({"registry_sha256": "a" * 64}, "registry_pin_mismatch"),
        ({"manifest_sha256": "b" * 64}, "manifest_pin_mismatch"),
        ({"reference_id": "synthetic.unregistered"}, "reference_not_registered"),
    ],
)
def test_mixed_or_stale_pins_never_substitute_the_current_reference(store, pin_change, reason):
    result = authenticate({**store.pin, **pin_change})
    assert result["status"] == "unconfirmed"
    assert result["reason_codes"] == [reason]
    assert result["claims"] == []
    assert all(result[key] == value for key, value in pin_change.items())


def test_other_catalogue_request_is_not_authenticated(store):
    result = authenticate(store, catalogue={**PIN, "work_id": "w_other"})
    assert result["status"] == "unconfirmed"
    assert result["reason_codes"] == ["work_mismatch"]


@pytest.mark.parametrize(
    "mutation, reason",
    [
        ("artifact_changed", "reference_artifact_mismatch"),
        ("artifact_missing", "reference_artifact_unavailable"),
        ("artifact_symlink", "reference_artifact_unavailable"),
        ("artifact_writable", "trust_file_writable"),
        ("evidence_changed", "evidence_digest_mismatch"),
        ("evidence_symlink", "evidence_unavailable"),
        ("manifest_changed", "manifest_digest_mismatch"),
        ("manifest_missing", "manifest_unavailable"),
        ("manifest_directory_symlink", "manifest_unavailable"),
    ],
)
def test_store_mutation_and_symlinks_refuse_authentication(store, mutation, reason):
    artifact = store.root / "artifacts" / trust_store.sha(ARTIFACT)
    evidence = store.root / "evidence" / store.evidence["receipt"]
    manifest = store.root / "manifests" / (store.manifest_sha256 + ".json")
    if mutation == "artifact_changed":
        trust_store.put(artifact.parent, artifact.name, ARTIFACT[:-1] + b"X")
    elif mutation == "artifact_missing":
        artifact.unlink()
    elif mutation == "artifact_symlink":
        target = store.root / "elsewhere"
        os.rename(artifact, target)
        os.symlink(target, artifact)
    elif mutation == "artifact_writable":
        trust_store.writable(artifact)
    elif mutation == "evidence_changed":
        trust_store.put(evidence.parent, evidence.name, b"altered evidence")
    elif mutation == "evidence_symlink":
        target = store.root / "elsewhere"
        os.rename(evidence, target)
        os.symlink(target, evidence)
    elif mutation == "manifest_changed":
        trust_store.put(manifest.parent, manifest.name, manifest.read_bytes() + b" ")
    elif mutation == "manifest_missing":
        manifest.unlink()
    elif mutation == "manifest_directory_symlink":
        os.rename(store.root / "manifests", store.root / "manifests-real")
        os.symlink("manifests-real", store.root / "manifests")
    result = authenticate(store)
    assert result["status"] == "unconfirmed"
    assert reason in result["reason_codes"]
    assert result["claims"] == []


@pytest.mark.parametrize(
    "raw, reason",
    [
        (b'{"schema": "x"}', "manifest_invalid"),
        (b"\xff\xfe", "manifest_invalid"),
        (b"[]", "manifest_invalid"),
        (b"{}" + b" " * (64 * 1024), "manifest_invalid"),
    ],
    ids=[
        "wrong-schema",
        "invalid-encoding",
        "array",
        "oversized-manifest",
    ],
)
def test_malformed_manifest_bytes_are_refused(store, unconfigured, raw, reason):
    trust_store.raw_manifest(store, raw)
    trust_store.configure_raw_registry(store, unconfigured, json.dumps(store.registry).encode())
    result = authenticate(store)
    assert result["status"] == "unconfirmed"
    assert result["reason_codes"] == [reason]


def test_manifest_with_duplicate_key_or_extra_key_is_invalid(store, unconfigured):
    text = json.dumps(store.manifest)
    for raw in (
        text[:-1] + ', "schema": "librarium.complete-content-reference.v1"}',
        json.dumps({**store.manifest, "public_key": "self-supplied"}),
        json.dumps({**store.manifest, "artifact": {**store.manifest["artifact"], "size": True}}),
        json.dumps({**store.manifest, "artifact": {**store.manifest["artifact"], "format": "pdf"}}),
    ):
        trust_store.raw_manifest(store, raw.encode())
        trust_store.configure_raw_registry(store, unconfigured, json.dumps(store.registry).encode())
        result = authenticate(store)
        assert result["status"] == "unconfirmed"
        assert result["reason_codes"] == ["manifest_invalid"]


def test_registry_changed_during_check_is_unconfirmed(store, monkeypatch):
    original = content_trust._verify_artifact

    def changed(*args, **kwargs):
        value = original(*args, **kwargs)
        trust_store.put(store.root, "registry.json", store.path.read_bytes() + b" ")
        return value

    monkeypatch.setattr(content_trust, "_verify_artifact", changed)
    result = authenticate(store)
    assert result["status"] == "unconfirmed"
    assert result["reason_codes"] == ["trust_store_changed"]


def test_checkpoint_receives_reference_bytes_and_may_cancel(store):
    seen = []

    def checkpoint(count):
        seen.append(count)

    authenticate(store, checkpoint=checkpoint)
    assert sum(seen) >= len(ARTIFACT)

    class Cancelled(Exception):
        pass

    def cancel(count):
        raise Cancelled

    with pytest.raises(Cancelled):
        authenticate(store, checkpoint=cancel)


def test_pin_validation_refuses_malformed_selection():
    good = {
        "reference_id": "synthetic.reference-1",
        "registry_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
    }
    content_trust.validate_pin(good)
    for bad in (
        None,
        [],
        {**good, "extra": 1},
        {k: v for k, v in good.items() if k != "manifest_sha256"},
        {**good, "registry_sha256": "A" * 64},
        {**good, "reference_id": ""},
        {**good, "reference_id": "../escape"},
        {**good, "reference_id": "x" * 81},
        {**good, "reference_id": 7},
    ):
        with pytest.raises(content_trust.TrustError):
            content_trust.validate_pin(bad)


@pytest.mark.parametrize(
    "registry, digest",
    [
        ("/trust/registry.json", ""),
        ("", "a" * 64),
        ("relative/registry.json", "a" * 64),
        ("/trust/../registry.json", "a" * 64),
        ("/trust/registry.json", "A" * 64),
        ("/trust/registry.json", "a" * 63),
    ],
)
def test_trust_settings_require_one_absolute_registry_and_its_digest(monkeypatch, registry, digest):
    from test_deployment import settings_result

    monkeypatch.setenv("LIBRARIUM_CONTENT_TRUST_REGISTRY", registry)
    monkeypatch.setenv("LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256", digest)
    assert settings_result("", "0").returncode != 0


def test_trust_settings_are_optional_and_paired(monkeypatch):
    from test_deployment import settings_result

    monkeypatch.delenv("LIBRARIUM_CONTENT_TRUST_REGISTRY", raising=False)
    monkeypatch.delenv("LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256", raising=False)
    assert settings_result("", "0").returncode == 0
    monkeypatch.setenv("LIBRARIUM_CONTENT_TRUST_REGISTRY", "/trust/registry.json")
    monkeypatch.setenv("LIBRARIUM_CONTENT_TRUST_REGISTRY_SHA256", "a" * 64)
    assert settings_result("", "0").returncode == 0
