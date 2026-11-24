import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def workflow(name):
    return yaml.safe_load((ROOT / f".github/workflows/{name}.yml").read_text())


def test_browser_artifact_is_exported_after_browser_acceptance_without_rebuild():
    steps = workflow("container")["jobs"]["candidate-container"]["steps"]
    names = [step.get("name") for step in steps]
    export = steps[names.index("Export the accepted source browser")]
    assert names.index("Source browser isolation and Chromium sandbox") < names.index(
        export["name"]
    )
    assert export["if"] == "inputs.export-image"
    assert "docker save librarium-source-browser:ci" in export["run"]
    assert "accepted-images" in export["run"]
    assert "docker build" not in export["run"]
    upload = next(
        step
        for step in steps
        if step.get("with", {}).get("name", "").startswith("${{ inputs.export-image")
    )
    assert "librarium-source-browser-image.tar.gz" in upload["with"]["path"]
    assert "accepted-images.json" in upload["with"]["path"]


def test_beta_checks_loaded_pair_and_registry_pair_before_release_is_visible():
    steps = workflow("beta")["jobs"]["publish"]["steps"]
    run = "\n".join(step.get("run", "") for step in steps)
    assert "verify-images" in run
    assert "librarium-source-browser-image.tar.gz" in run
    assert "docker image inspect librarium-source-browser:ci" in run
    assert 'scripts/registry.py digest "$VERSION" --role=source-browser' in run
    assert '--browser-digest="$BROWSER_DIGEST"' in run
    assert run.index('scripts/registry.py digest "$VERSION" --role=source-browser') < run.index(
        "gh release create"
    )
    assert "stack-assets.zip" in run
    assert "scripts/check_public_content.py" in run
    assert re.search(r"--draft(?![=\w-])", run)
    assert run.index("gh release view") < run.index("--draft=false")


def test_promotion_requires_explicit_browser_digest_in_both_stages():
    data = workflow("promote")
    assert data[True]["workflow_dispatch"]["inputs"]["browser-digest"]["required"] is True
    for job in data["jobs"].values():
        run = "\n".join(step.get("run", "") for step in job["steps"])
        assert '--browser-digest="$BROWSER_DIGEST"' in run
