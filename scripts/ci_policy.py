"""Inspect workflow data from GitHub without executing a pull request's checkout."""

import argparse
import base64
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import yaml

MAX_FILE = 256 * 1024
MAX_TOTAL = 1024 * 1024
MAX_WORKFLOWS = 32
POLICY = ".github/workflows/ci-policy.yml"
REQUIRED = {
    ".github/workflows/quality.yml": "source-quality",
    ".github/workflows/container.yml": "container",
}
RELEASES = {".github/workflows/beta.yml", ".github/workflows/promote.yml"}

WORKFLOW_FREE = {"name", "concurrency", "jobs"}
JOB_FREE = {"name", "timeout-minutes", "env", "steps"}


class Refused(ValueError):
    pass


class WorkflowLoader(yaml.SafeLoader):
    pass


WorkflowLoader.yaml_implicit_resolvers = {
    key: [(tag, match) for tag, match in values if tag != "tag:yaml.org,2002:bool"]
    for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
WorkflowLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(true|false)$"), list("tf")
)


def mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str) or key in result:
            raise Refused("yaml_mapping_refused")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


WorkflowLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def parse(content):
    if not isinstance(content, bytes) or len(content) > MAX_FILE:
        raise Refused("workflow_size_refused")
    try:
        depth = 0
        for count, event in enumerate(yaml.parse(content), 1):
            if isinstance(event, yaml.events.AliasEvent) or getattr(
                event, "anchor", None
            ):
                raise Refused("yaml_alias_refused")
            if isinstance(
                event, (yaml.events.MappingStartEvent, yaml.events.SequenceStartEvent)
            ):
                depth += 1
            if isinstance(
                event, (yaml.events.MappingEndEvent, yaml.events.SequenceEndEvent)
            ):
                depth -= 1
            if count > 50000 or depth > 40:
                raise Refused("yaml_complexity_refused")
        value = yaml.load(content, Loader=WorkflowLoader)
        if not isinstance(value, dict):
            raise Refused("workflow_mapping_required")
        return value
    except (yaml.YAMLError, UnicodeError, RecursionError) as error:
        raise Refused("yaml_invalid") from error


def workflow_path(path):
    return path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))


def local_workflows(root):
    folder = root / ".github" / "workflows"
    if (root / ".github").is_symlink() or folder.is_symlink():
        raise Refused("workflow_symlink_refused")
    result = {}
    for path in folder.rglob("*"):
        if path.is_symlink():
            raise Refused("workflow_symlink_refused")
        relative = path.relative_to(root).as_posix()
        if path.is_file() and workflow_path(relative):
            if path.stat().st_size > MAX_FILE:
                raise Refused("workflow_size_refused")
            result[relative] = path.read_bytes()
    check_sizes(result)
    return result


def check_sizes(workflows):
    if len(workflows) > MAX_WORKFLOWS or sum(map(len, workflows.values())) > MAX_TOTAL:
        raise Refused("workflow_budget_refused")


def events(document):
    value = document.get("on")
    if isinstance(value, str):
        return {value: None}
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return dict.fromkeys(value)
    return value if isinstance(value, dict) else {}


def contains_secrets(value, condition=False):
    if isinstance(value, str):
        expressions = [value] if condition else re.findall(r"\$\{\{(.*?)\}\}", value, re.DOTALL)
        return any(re.search(r"\bsecrets\s*(?:\.|\[)", item) for item in expressions)
    if isinstance(value, dict):
        return "secrets" in value or any(
            contains_secrets(item, condition=key == "if") for key, item in value.items()
        )
    if isinstance(value, list):
        return any(contains_secrets(item) for item in value)
    return False


def permissions_allowed(value, release_publish=False):
    if not isinstance(value, dict):
        return False
    return all(
        isinstance(key, str)
        and (
            permission in ("none", "read")
            or (
                release_publish
                and key in ("contents", "packages")
                and permission == "write"
            )
        )
        for key, permission in value.items()
    )


def harness(document, free, *, normalize_events=False):
    result = {key: value for key, value in document.items() if key not in free}
    if normalize_events and "on" in result:
        result["on"] = events(document)
    return result


def sha_pinned(uses):
    return (
        isinstance(uses, str)
        and not uses.startswith("./")
        and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[^\s@]+)?@[0-9a-fA-F]{40}", uses)
        is not None
    )


def local_action(uses):
    return (
        isinstance(uses, str)
        and re.fullmatch(r"\./[^\s@]+", uses) is not None
        and all(part not in ("", ".", "..") for part in uses[2:].split("/"))
    )


def job_harness_changed(jobs, baseline_jobs):
    if (
        not isinstance(jobs, dict)
        or not isinstance(baseline_jobs, dict)
        or jobs.keys() != baseline_jobs.keys()
    ):
        return True
    for name, job in jobs.items():
        baseline = baseline_jobs[name]
        if not isinstance(job, dict) or not isinstance(baseline, dict):
            return True
        if harness(job, JOB_FREE) != harness(baseline, JOB_FREE):
            return True
        steps = job.get("steps", [])
        baseline_steps = baseline.get("steps", [])
        if not isinstance(steps, list) or not isinstance(baseline_steps, list):
            return True
        if "uses" not in job and not steps:
            return True
        baseline_uses = [
            step["uses"] for step in baseline_steps if isinstance(step, dict) and "uses" in step
        ]
        for step in steps:
            if (
                isinstance(step, dict)
                and "uses" in step
                and step["uses"] not in baseline_uses
                and not sha_pinned(step["uses"])
            ):
                return True
    return False


def workflow_harness_changed(document, baseline):
    candidate = harness(document, WORKFLOW_FREE, normalize_events=True)
    trusted = harness(baseline, WORKFLOW_FREE, normalize_events=True)
    trigger = candidate.get("on", {})
    baseline_trigger = trusted.get("on", {})
    for name in trigger.keys() - baseline_trigger.keys():
        if name not in {"push", "schedule", "workflow_dispatch"}:
            return True
        if name == "push" and trigger[name] != {"branches": ["main"]}:
            return True
    candidate["on"] = {name: value for name, value in trigger.items() if name in baseline_trigger}
    return candidate != trusted


def validate(workflows, trusted):
    check_sizes(workflows)
    errors = set()
    documents = {}
    for path, content in workflows.items():
        try:
            documents[path] = parse(content)
        except Refused as error:
            errors.add(str(error))
    for path, document in documents.items():
        trigger = events(document)
        allowed_events = {
            "pull_request",
            "push",
            "schedule",
            "workflow_call",
            "workflow_dispatch",
        }
        if path == POLICY:
            allowed_events.add("pull_request_target")
            if path not in trusted or document != parse(trusted[path]):
                errors.add("trusted_policy_workflow_changed")
        if not trigger or not set(trigger) <= allowed_events:
            errors.add("event_refused")
        if contains_secrets(document):
            errors.add("secrets_refused")
        policy_permissions = path == POLICY and document.get("permissions") == {
            "contents": "read",
            "checks": "write",
        }
        if not policy_permissions and not permissions_allowed(
            document.get("permissions")
        ):
            errors.add("token_permissions_refused")
        jobs = document.get("jobs")
        if not isinstance(jobs, dict) or not jobs:
            errors.add("jobs_required")
            if not isinstance(jobs, dict):
                errors.add("job_mapping_required")
            continue
        if path in RELEASES and set(trigger) != {"workflow_dispatch"}:
            errors.add("release_event_refused")
        for name, job in jobs.items():
            if not isinstance(job, dict):
                errors.add("job_mapping_required")
                continue
            if "permissions" in job and not permissions_allowed(
                job["permissions"], path in RELEASES and name == "publish"
            ):
                errors.add("token_permissions_refused")
            status = job.get("name", name)
            if not isinstance(status, str) or "${{" in status:
                errors.add("job_name_refused")
            for required_path, required_job in REQUIRED.items():
                if (name == required_job or status == required_job) and (
                    path != required_path
                    or name != required_job
                    or status != required_job
                ):
                    errors.add("required_status_shadowed")
            if path != POLICY and any(
                isinstance(value, str)
                and value.strip().casefold() in {"ci-policy", "inspect ci policy"}
                for value in (name, status)
            ):
                errors.add("required_status_shadowed")
            if "uses" in job:
                if (
                    path not in RELEASES
                    or job["uses"]
                    not in (
                        "./.github/workflows/quality.yml",
                        "./.github/workflows/container.yml",
                    )
                    or "runs-on" in job
                ):
                    errors.add("reusable_workflow_refused")
            elif job.get("runs-on") != "ubuntu-24.04":
                errors.add("runner_route_refused")
            steps = job.get("steps", [])
            if not isinstance(steps, list) or ("uses" not in job and not steps):
                errors.add("steps_required")
                continue
            for step in steps:
                if not isinstance(step, dict):
                    errors.add("step_mapping_required")
                else:
                    if "uses" in step and not (
                        local_action(step["uses"]) or sha_pinned(step["uses"])
                    ):
                        errors.add("step_uses_unpinned")
                    if str(step.get("uses", "")).lower().startswith("actions/checkout@"):
                        inputs = step.get("with", {})
                        if not isinstance(inputs, dict):
                            errors.add("step_mapping_required")
                        elif inputs.get("persist-credentials") is not False:
                            errors.add("checkout_credentials_refused")
    for path, name in REQUIRED.items():
        document = documents.get(path)
        if document is None:
            errors.add("required_workflow_missing")
            continue
        if events(document).get("pull_request", False) is not None:
            errors.add("required_trigger_changed")
        jobs = document.get("jobs")
        job = jobs.get(name) if isinstance(jobs, dict) else None
        baseline_document = parse(trusted[path]) if path in trusted else {}
        if workflow_harness_changed(document, baseline_document):
            errors.add("required_workflow_changed")
        if not job or job_harness_changed(document.get("jobs"), baseline_document.get("jobs")):
            errors.add("required_job_changed")
    if POLICY not in documents:
        errors.add("trusted_policy_workflow_missing")
    return sorted(errors)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise Refused("github_redirect_refused")


def github_json(endpoint, payload=None):
    if not endpoint.startswith("/repos/") or any(char in endpoint for char in "\r\n"):
        raise Refused("github_endpoint_refused")
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        "https://api.github.com" + endpoint,
        data=data,
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "librarium-ci-policy",
            "Content-Type": "application/json",
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=30) as response:
        content = response.read(16 * 1024 * 1024 + 1)
    if len(content) > 16 * 1024 * 1024:
        raise Refused("github_response_budget_refused")
    return json.loads(content)


def validate_tree(tree):
    if (
        not isinstance(tree, dict)
        or tree.get("truncated")
        or not isinstance(tree.get("tree"), list)
    ):
        raise Refused("github_tree_refused")
    found = []
    for entry in tree["tree"]:
        path = entry.get("path", "")
        if path in (".github", ".github/workflows") and entry.get("type") != "tree":
            raise Refused("workflow_symlink_refused")
        if path.startswith(".github/workflows/") and entry.get("mode") in (
            "120000",
            "160000",
        ):
            raise Refused("workflow_symlink_refused")
        if workflow_path(path):
            if entry.get("type") != "blob" or entry.get("mode") not in (
                "100644",
                "100755",
            ):
                raise Refused("workflow_symlink_refused")
            if not isinstance(entry.get("size"), int) or entry["size"] > MAX_FILE:
                raise Refused("workflow_size_refused")
            if not re.fullmatch("[0-9a-f]{40}", entry.get("sha", "")):
                raise Refused("github_blob_refused")
            found.append(entry)
    if len(found) > MAX_WORKFLOWS or sum(item["size"] for item in found) > MAX_TOTAL:
        raise Refused("workflow_budget_refused")
    return found


def remote_workflows(repository, revision):
    if not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
    ) or not re.fullmatch("[0-9a-f]{40}", revision):
        raise Refused("github_identity_refused")
    entries = validate_tree(
        github_json(f"/repos/{repository}/git/trees/{revision}?recursive=1")
    )
    workflows = {}
    for entry in entries:
        blob = github_json(f"/repos/{repository}/git/blobs/{entry['sha']}")
        if blob.get("encoding") != "base64" or blob.get("size") != entry["size"]:
            raise Refused("github_blob_refused")
        content = base64.b64decode(blob["content"].replace("\n", ""), validate=True)
        if len(content) != entry["size"]:
            raise Refused("github_blob_refused")
        workflows[entry["path"]] = content
    return workflows


def check_identity(repository, revision):
    if not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
    ) or not re.fullmatch("[0-9a-f]{40}", revision):
        raise Refused("github_identity_refused")


def publish_check(repository, revision, errors):
    check_identity(repository, revision)
    return github_json(
        f"/repos/{repository}/check-runs",
        {
            "name": "ci-policy",
            "head_sha": revision,
            "status": "completed",
            "conclusion": "failure" if errors else "success",
            "output": {
                "title": "CI workflow policy",
                "summary": "Policy refused: " + ", ".join(errors)
                if errors
                else "Workflow data passed trusted-base inspection; candidate code was not executed.",
            },
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-file", type=Path)
    parser.add_argument("--local", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    repository = revision = None
    errors = []
    try:
        trusted = local_workflows(root)
        if args.event_file:
            event = json.loads(args.event_file.read_text())
            repository = os.environ["GITHUB_REPOSITORY"]
            pull = event["pull_request"]
            if pull["base"].get("ref") != "main":
                raise Refused("unprotected_base_refused")
            revision = pull["head"]["sha"]
            check_identity(repository, revision)
            if pull["base"]["repo"]["full_name"] != repository:
                raise Refused("github_repository_refused")
            workflows = remote_workflows(repository, revision)
        elif args.local:
            workflows = local_workflows(args.local)
        else:
            parser.error("choose --event-file or --local")
        errors = validate(workflows, trusted)
    except Exception:  # noqa: BLE001 - Unexpected validation errors must publish a failure check.
        errors = ["inspection_failed"]
    if args.event_file and repository is not None and revision is not None:
        try:
            publish_check(repository, revision, errors)
        except (OSError, KeyError, TypeError, ValueError):
            errors = ["status_publication_failed"]
    if errors:
        print("CI policy refused: " + ", ".join(errors))
        return 1
    print("CI policy passed: workflow data checked; no candidate code executed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
