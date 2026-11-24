"""The acceptance proof must reject unsafe resolved models before sanitizing fixtures."""

import copy
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "cover_acceptance",
    Path(__file__).resolve().parents[1] / ".github/scripts/cover_sources_container_acceptance.py",
)
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)


def model():
    return {
        "services": {
            "db": {"networks": {"default": {}}},
            "web": {"networks": {"default": {}, "edge": {}}, "environment": {}},
            "worker": {
                "networks": {"default": {}, "cover-control": {}},
                "environment": {"LIBRARIUM_COVER_SOURCES_SECRET": "x" * 32},
            },
            "cover-sources": {
                "networks": {"cover-control": {}, "cover-egress": {}},
                "environment": {"HARDCOVER_TOKEN": "", "LIBRARIUM_COVER_SOURCES_SECRET": "x" * 32},
            },
        },
        "networks": {
            "default": {"internal": True},
            "edge": {"internal": True},
            "cover-control": {"internal": True},
            "cover-egress": {"internal": False},
        },
    }


def test_safe_overlay_preserves_internal_edge_ingress():
    proof.validate_model(model())


@pytest.mark.parametrize(
    "mutation",
    [
        "mount",
        "db-network",
        "web-egress",
        "worker-egress",
        "secret",
        "ports",
        "public-edge",
        "no-edge",
    ],
)
def test_unsafe_resolved_facts_fail_before_fixture_rewrites(mutation):
    value = copy.deepcopy(model())
    role = value["services"]["cover-sources"]
    if mutation == "mount":
        role["volumes"] = [{"target": "/library"}]
    if mutation == "db-network":
        role["networks"]["default"] = {}
    if mutation == "web-egress":
        value["services"]["web"]["networks"]["cover-egress"] = {}
    if mutation == "worker-egress":
        value["services"]["worker"]["networks"]["cover-egress"] = {}
    if mutation == "secret":
        role["environment"]["PGPASSWORD"] = "unsafe"
    if mutation == "ports":
        role["ports"] = [8124]
    if mutation == "public-edge":
        value["networks"]["edge"]["internal"] = False
    if mutation == "no-edge":
        del value["services"]["web"]["networks"]["edge"]
    with pytest.raises(AssertionError):
        proof.validate_model(value)


def test_google_key_is_optional_and_source_only():
    value = model()
    value["services"]["cover-sources"]["environment"]["GOOGLE_BOOKS_API_KEY"] = "fixture-key"
    proof.validate_model(value)
    for role in ("web", "worker", "db"):
        unsafe = copy.deepcopy(value)
        unsafe["services"][role].setdefault("environment", {})["GOOGLE_BOOKS_API_KEY"] = "fixture-key"
        with pytest.raises(AssertionError):
            proof.validate_model(unsafe)
