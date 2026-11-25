import os
import re
import subprocess
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
    upload = next(step for step in steps if step.get("name") == "Retain encrypted accepted images")
    assert "librarium-source-browser-image.tar.gz.cms" in upload["with"]["path"]
    assert "accepted-images.json" in upload["with"]["path"]


def test_beta_verifies_rehearsal_and_staged_pair_before_release_is_visible():
    jobs = workflow("beta")["jobs"]
    rehearsal = "\n".join(step.get("run", "") for step in jobs["rehearsal"]["steps"])
    publish = "\n".join(step.get("run", "") for step in jobs["publish"]["steps"])
    assert "verify-images" in rehearsal
    assert "scripts/check_public_content.py" in rehearsal
    assert "verify-rehearsal" in publish
    assert publish.count('scripts/registry.py verify-pair "$VERSION"') >= 3
    assert publish.index("verify-rehearsal") < publish.index("gh release create")
    assert "stack-assets.zip" in publish
    assert re.search(r"--draft(?![=\w-])", publish)
    assert publish.index("verify-assets") < publish.index("--draft=false")


def test_promotion_requires_explicit_browser_digest_in_both_stages():
    data = workflow("promote")
    assert data[True]["workflow_dispatch"]["inputs"]["browser-digest"]["required"] is True
    for job in data["jobs"].values():
        run = "\n".join(step.get("run", "") for step in job["steps"])
        assert '--browser-digest="$BROWSER_DIGEST"' in run


def test_beta_requires_public_main_and_exact_reviewed_workflow_commit_before_acceptance():
    jobs = workflow("beta")["jobs"]
    validate = jobs["validate"]["steps"]
    run = next(
        step["run"]
        for step in validate
        if step.get("name") == "Verify main source and unused version"
    )
    assert 'test "$GITHUB_REPOSITORY" = jshauns81/librarium-public' in run
    assert 'test "$GITHUB_REF" = refs/heads/main' in run
    assert 'test "$SOURCE_SHA" = "$GITHUB_SHA"' in run
    assert jobs["quality"]["needs"] == "validate"
    assert jobs["acceptance"]["needs"] == "validate"
    assert set(jobs["rehearsal"]["needs"]) == {"validate", "quality", "acceptance"}
    assert jobs["publish"]["needs"] == "validate"


def test_beta_finalizes_only_staged_images_from_reviewed_source():
    job = workflow("beta")["jobs"]["publish"]
    steps = job["steps"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "${{ inputs.source-sha }}"
    run = "\n".join(step.get("run", "") for step in steps)
    assert 'test "$(git rev-parse HEAD)" = "$SOURCE_SHA"' in run
    assert "verify-rehearsal" in run and "verify-pair" in run
    assert "docker push" not in run
    assert job["permissions"]["packages"] == "read"


def test_beta_defaults_to_rehearsal_and_preserves_preflight_artifacts():
    data = workflow("beta")
    publish_input = data[True]["workflow_dispatch"]["inputs"]["publish"]
    assert publish_input["type"] == "boolean"
    assert publish_input["default"] is False
    assert data["jobs"]["rehearsal"]["if"] == "${{ !inputs.publish }}"
    assert data["jobs"]["publish"]["if"] == "${{ inputs.publish }}"
    steps = data["jobs"]["rehearsal"]["steps"]
    run = "\n".join(step.get("run", "") for step in steps)
    artifact = next(step for step in steps if step.get("name") == "Retain release preflight assets")
    assert "manifest-preflight.json" in run and "stack-assets.zip" in run
    assert artifact["with"]["name"] == "release-preflight-${{ github.run_attempt }}"


def test_exported_image_receipt_requires_checkout_to_match_requested_commit():
    steps = workflow("container")["jobs"]["candidate-container"]["steps"]
    export = next(
        step for step in steps if step.get("name") == "Export the accepted source browser"
    )
    assert export["env"]["SOURCE_SHA"] == "${{ inputs.source-sha }}"
    assert 'test "$(git rev-parse HEAD)" = "$SOURCE_SHA"' in export["run"]
    assert export["run"].index('test "$(git rev-parse HEAD)" = "$SOURCE_SHA"') < export[
        "run"
    ].index("accepted-images")


def test_candidate_registry_configuration_uses_the_public_image():
    steps = workflow("container")["jobs"]["candidate-container"]["steps"]
    step = next(
        step for step in steps if step.get("name") == "Validate registry-only configuration"
    )
    assert 'LIBRARIUM_IMAGE="ghcr.io/jshauns81/librarium-public@' in step["run"]


def test_beta_acceptance_grants_reusable_workflow_required_permissions():
    caller = workflow("beta")["jobs"]["acceptance"]["permissions"]
    callee = workflow("container")["jobs"]["candidate-container"]["permissions"]
    assert caller["contents"] == callee["contents"] == "read"
    assert caller["packages"] == callee["packages"] == "read"


def test_rejects_unreviewed_dispatch_before_running_release_checks(tmp_path):
    step = next(
        step
        for step in workflow("beta")["jobs"]["validate"]["steps"]
        if step.get("name") == "Verify main source and unused version"
    )
    guard = step["run"].split("python3 scripts/release.py", 1)[0]
    git = tmp_path / "git"
    git.write_text('#!/bin/sh\nprintf "%s\\n" "$SOURCE_SHA"\n')
    git.chmod(0o755)
    sha = "a" * 40
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "GITHUB_REPOSITORY": "jshauns81/librarium-public",
        "GITHUB_REF": "refs/heads/main",
        "SOURCE_SHA": sha,
        "GITHUB_SHA": sha,
    }
    assert subprocess.run(["bash", "-e", "-c", guard], env=env, check=False).returncode == 0
    for key, value in (
        ("GITHUB_REPOSITORY", "other/librarium-public"),
        ("GITHUB_REF", "refs/heads/other"),
        ("GITHUB_SHA", "b" * 40),
    ):
        assert (
            subprocess.run(
                ["bash", "-e", "-c", guard], env={**env, key: value}, check=False
            ).returncode
            != 0
        )


def test_beta_rechecks_staged_pair_before_and_after_draft_release():
    steps = workflow("beta")["jobs"]["publish"]["steps"]
    run = "\n".join(step.get("run", "") for step in steps)
    assert run.count('scripts/registry.py verify-pair "$VERSION" --commit="$SOURCE_SHA"') >= 3
    assert run.index("verify-pair") < run.index("gh release create")
    assert run.rindex("verify-pair") < run.index("--draft=false")


def test_candidate_upgrade_runs_locally_before_only_encrypted_image_export():
    jobs = workflow("container")["jobs"]
    candidate = jobs["candidate-container"]["steps"]
    names = [step.get("name") for step in candidate]
    classification = next(
        step for step in candidate if step.get("name") == "Select candidate upgrade tier"
    )
    assert "container_tiers.py classify" in classification["run"]
    upgrade = next(
        step for step in candidate if step.get("name") == "Upgrade the local accepted candidate"
    )
    assert upgrade["if"] == "steps.areas.outputs.populated_upgrade == 'true'"
    assert names.index("Upgrade the local accepted candidate") < names.index(
        "Export the accepted source browser"
    )
    upload = next(
        step for step in candidate if step.get("name") == "Retain encrypted accepted images"
    )
    paths = upload["with"]["path"]
    assert "librarium-image.tar.gz.cms" in paths
    assert "librarium-source-browser-image.tar.gz.cms" in paths
    assert "accepted-images.json" in paths
    assert all(not line.strip().endswith(".tar.gz") for line in paths.splitlines())
    assert not any("upgrade-image" in str(step) for step in candidate)


def test_exported_archives_are_cms_sealed_and_decrypt_to_exact_images(tmp_path):
    import gzip

    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=fixture",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    (tmp_path / "git").write_text('#!/bin/sh\nprintf "%s\\n" "$SOURCE_SHA"\n')
    (tmp_path / "docker").write_text(
        '#!/bin/sh\nif [ "$1" = save ]; then printf "%s" "$2"; else printf "sha256:%064d\\n" 0; fi\n'
    )
    for name in ("git", "docker"):
        (tmp_path / name).chmod(0o755)
    runner = tmp_path / "runner"
    runner.mkdir()
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "RUNNER_TEMP": str(runner),
        "REVIEW_CERT": cert.read_text(),
        "SOURCE_SHA": "a" * 40,
        "EXPECTED_IMAGE_ID": "sha256:" + "0" * 64,
    }
    step = next(
        step
        for step in workflow("container")["jobs"]["candidate-container"]["steps"]
        if step.get("name") == "Export the accepted source browser"
    )
    subprocess.run(
        ["bash", "-eo", "pipefail", "-c", step["run"]],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    for name, image in (
        ("librarium-image", "librarium:ci"),
        ("librarium-source-browser-image", "librarium-source-browser:ci"),
    ):
        sealed = runner / "sealed-images" / f"{name}.tar.gz.cms"
        result = subprocess.run(
            [
                "openssl",
                "cms",
                "-decrypt",
                "-binary",
                "-inform",
                "DER",
                "-in",
                str(sealed),
                "-recip",
                str(cert),
                "-inkey",
                str(key),
            ],
            capture_output=True,
            check=True,
        )
        assert gzip.decompress(result.stdout) == image.encode()
        assert not (runner / f"{name}.tar.gz").exists()


def test_upgrade_proof_verifier_rejects_other_commit_or_image(tmp_path):
    import json

    proof_dir = tmp_path / "populated-proof"
    proof_dir.mkdir()
    commit = "a" * 40
    image_id = "sha256:" + "b" * 64
    proof = {
        "schema": "librarium.populated-upgrade.v2",
        "outcome": "passed",
        "runtime": "image",
        "candidate": {"commit": commit},
        "builds": {"current": image_id},
    }
    fake_git = tmp_path / "git"
    fake_git.write_text(f'#!/bin/sh\nprintf "%s\\n" "{commit}"\n')
    fake_git.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "CANDIDATE_IMAGE": image_id,
    }
    step = next(
        step
        for step in workflow("container")["jobs"]["populated-upgrade"]["steps"]
        if step.get("name") == "Verify proof binds the accepted source and image"
    )
    for mutation, expected in (
        ({}, 0),
        ({"candidate": {"commit": "c" * 40}}, 1),
        ({"builds": {"current": "sha256:" + "d" * 64}}, 1),
        ({"outcome": "failed"}, 1),
    ):
        (proof_dir / "result.json").write_text(json.dumps({**proof, **mutation}))
        assert (
            subprocess.run(
                ["bash", "-e", "-c", step["run"]], env=env, capture_output=True, check=False
            ).returncode
            == expected
        )


def test_export_fails_before_creating_images_if_review_certificate_is_invalid(tmp_path):
    git = tmp_path / "git"
    git.write_text('#!/bin/sh\nprintf "%s\\n" "$SOURCE_SHA"\n')
    git.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "SOURCE_SHA": "a" * 40,
        "REVIEW_CERT": "not a certificate",
    }
    step = next(
        step
        for step in workflow("container")["jobs"]["candidate-container"]["steps"]
        if step.get("name") == "Export the accepted source browser"
    )
    result = subprocess.run(
        ["bash", "-eo", "pipefail", "-c", step["run"]],
        cwd=ROOT,
        env=env,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert list((tmp_path / "sealed-images").iterdir()) == []
    assert not list(tmp_path.glob("*.tar.gz"))
