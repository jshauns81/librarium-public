import copy
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ci_policy", ROOT / "scripts/ci_policy.py")
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.workflows = policy.local_workflows(ROOT)

    def check(self, workflows=None):
        return policy.validate(self.workflows if workflows is None else workflows, self.workflows)

    def change(self, filename, mutate):
        workflows = copy.deepcopy(self.workflows)
        document = policy.parse(workflows[filename])
        mutate(document)
        workflows[filename] = policy.yaml.safe_dump(document).encode()
        return workflows

    def test_current_workflows_pass(self):
        self.assertEqual([], self.check())

    def routed_workflows(self, runner):
        workflows = dict(self.workflows)
        for filename in (
            "quality.yml",
            "container.yml",
            "delivery-writer.yml",
            "beta.yml",
            "promote.yml",
        ):
            path = ".github/workflows/" + filename
            document = policy.parse(workflows[path])
            for job in document["jobs"].values():
                if "uses" not in job:
                    job["runs-on"] = copy.deepcopy(runner)
            workflows[path] = policy.yaml.safe_dump(document).encode()
        return workflows

    def test_only_the_literal_hosted_runner_passes(self):
        baseline = self.routed_workflows("ubuntu-24.04")
        self.assertEqual([], policy.validate(baseline, baseline))

    def test_runner_selection_rejects_pools_and_expressions(self):
        baseline = self.routed_workflows("ubuntu-24.04")
        for runner in (
            "${{ fromJSON(vars.CI_RUNS_ON || '\"ubuntu-24.04\"') }}",
            ["ubuntu-24.04"],
            "ubuntu-latest",
            "self-hosted",
            ["self-hosted", "linux", "x64"],
            ["self-hosted", "linux", "x64", "example-pool", "other"],
            ["self-hosted", "linux", "x64", "legacy-runner"],
            "${{ fromJSON(vars.OTHER_RUNNER) }}",
            "${{ fromJSON(vars.CI_RUNS_ON) }}",
            "${{ matrix.runner }}",
            {"group": "example-pool"},
        ):
            with self.subTest(runner=runner):
                workflows = self.routed_workflows(runner)
                self.assertIn("runner_route_refused", policy.validate(workflows, baseline))

    def test_policy_always_requires_a_literal_hosted_runner(self):
        for runner in (
            "${{ fromJSON(vars.CI_RUNS_ON || '\"ubuntu-24.04\"') }}",
            ["self-hosted", "linux", "x64", "example-pool"],
        ):
            with self.subTest(runner=runner):
                workflows = self.routed_workflows("ubuntu-24.04")
                document = policy.parse(workflows[".github/workflows/ci-policy.yml"])
                document["jobs"]["ci-policy"]["runs-on"] = runner
                workflows[".github/workflows/ci-policy.yml"] = policy.yaml.safe_dump(
                    document
                ).encode()
                self.assertIn("runner_route_refused", policy.validate(workflows, workflows))

    def test_self_hosted_routes_cannot_be_added_to_unapproved_workflows(self):
        for runner in (
            "${{ fromJSON(vars.CI_RUNS_ON || '\"ubuntu-24.04\"') }}",
            ["self-hosted", "linux", "x64", "example-pool"],
        ):
            with self.subTest(runner=runner):
                workflows = self.routed_workflows("ubuntu-24.04")
                workflows[".github/workflows/extra.yml"] = policy.yaml.safe_dump(
                    {
                        "on": "pull_request",
                        "permissions": {"contents": "read"},
                        "jobs": {"extra": {"runs-on": runner, "steps": [{"run": "true"}]}},
                    }
                ).encode()
                self.assertIn("runner_route_refused", policy.validate(workflows, workflows))

    def test_hosted_runner_requirement_preserves_other_required_job_constraints(self):
        baseline = self.routed_workflows("ubuntu-24.04")
        workflows = dict(baseline)
        path = ".github/workflows/quality.yml"
        document = policy.parse(workflows[path])
        document["jobs"]["source-quality"]["continue-on-error"] = True
        workflows[path] = policy.yaml.safe_dump(document).encode()
        self.assertIn("required_job_changed", policy.validate(workflows, baseline))

    def test_required_run_text_can_change(self):
        for path, name in policy.REQUIRED.items():
            with self.subTest(path=path):

                def mutate(d, name=name):
                    step = next(s for s in d["jobs"][name]["steps"] if "run" in s)
                    step["run"] = "python3 -m unittest discover -s tests -q"

                self.assertEqual([], self.check(self.change(path, mutate)))

    def test_required_job_environment_can_be_added_or_changed(self):
        for path, name in policy.REQUIRED.items():
            with self.subTest(path=path):
                changed = self.change(
                    path,
                    lambda d, name=name: d["jobs"][name].update(
                        env={"LIBRARIUM_REQUIRE_LANDLOCK": "1"}
                    ),
                )
                self.assertEqual([], self.check(changed))

    def test_required_workflow_presentation_and_steps_can_change(self):
        def mutate(d):
            d["name"] = "Updated source checks"
            d["concurrency"] = {"group": "updated", "cancel-in-progress": True}
            job = d["jobs"]["source-quality"]
            job["name"] = "source-quality"
            job["timeout-minutes"] = 30
            job["steps"] = [s for s in job["steps"] if "uses" in s][::-1]
            for step in job["steps"]:
                step.update(name="Updated step", env={"EXAMPLE": "value"}, **{"if": "always()"})
                step.setdefault("with", {})["example-input"] = "updated"
            job["steps"].insert(0, {"name": "Additional check", "run": "true"})

        self.assertEqual([], self.check(self.change(".github/workflows/quality.yml", mutate)))

    def test_optional_job_display_name_can_change(self):
        changed = self.change(
            ".github/workflows/container.yml",
            lambda d: d["jobs"]["changes"].update(name="Classify changes"),
        )
        self.assertEqual([], self.check(changed))

    def test_required_root_harness_changes_refuse(self):
        for key, value in [
            ("on", {"pull_request": None, "workflow_dispatch": None}),
            ("permissions", {"contents": "none"}),
            ("env", {"EXAMPLE": "value"}),
            ("defaults", {"run": {"shell": "bash"}}),
        ]:
            with self.subTest(key=key):
                changed = self.change(
                    ".github/workflows/quality.yml",
                    lambda d, key=key, value=value: d.update({key: value}),
                )
                self.assertEqual(["required_workflow_changed"], self.check(changed))

    def test_required_job_harness_changes_refuse_in_every_job(self):
        for name in ("container", "changes"):
            for key, value in [
                ("runs-on", "ubuntu-22.04"),
                ("permissions", {"contents": "none"}),
                ("container", {"image": "example/image:latest"}),
                ("services", {"db": {"image": "example/db:latest"}}),
                ("environment", "example"),
                ("secrets", "inherit"),
                ("needs", ["example"]),
                ("if", "false"),
                ("defaults", {"run": {"shell": "bash"}}),
                ("strategy", {"matrix": {"example": [1, 2]}}),
                ("continue-on-error", True),
                ("outputs", {"example": "value"}),
            ]:
                with self.subTest(name=name, key=key):
                    changed = self.change(
                        ".github/workflows/container.yml",
                        lambda d, name=name, key=key, value=value: d["jobs"][name].update(
                            {key: value}
                        ),
                    )
                    self.assertIn("required_job_changed", self.check(changed))

    def test_required_job_set_cannot_change(self):
        for mutate in (
            lambda d: d["jobs"].update(
                extra={"runs-on": "ubuntu-24.04", "steps": [{"run": "true"}]}
            ),
            lambda d: d["jobs"].pop("candidate-container"),
            lambda d: d["jobs"].pop("container"),
        ):
            with self.subTest(mutate=mutate):
                changed = self.change(".github/workflows/container.yml", mutate)
                self.assertIn("required_job_changed", self.check(changed))

    def test_reusable_job_workflow_and_inputs_cannot_change(self):
        path = ".github/workflows/quality.yml"
        self.workflows = self.change(
            path,
            lambda d: d["jobs"].update(
                reusable={"uses": "./.github/workflows/example.yml", "with": {"example": "base"}}
            ),
        )
        for key, value in (
            ("uses", "./.github/workflows/other.yml"),
            ("with", {"example": "candidate"}),
        ):
            with self.subTest(key=key):
                changed = self.change(
                    path, lambda d, key=key, value=value: d["jobs"]["reusable"].update({key: value})
                )
                self.assertIn("required_job_changed", self.check(changed))

    def test_new_sha_pinned_step_action_passes(self):
        changed = self.change(
            ".github/workflows/quality.yml",
            lambda d: d["jobs"]["source-quality"]["steps"].append(
                {"uses": "example/action@" + "a" * 40}
            ),
        )
        self.assertEqual([], self.check(changed))

    def test_step_actions_require_local_path_or_full_sha_pin(self):
        for path, name in (
            (".github/workflows/quality.yml", "source-quality"),
            (".github/workflows/delivery-writer.yml", "native-role-proof"),
        ):
            for uses in (
                "example/action@v1",
                "example/action@main",
                "example/action@" + "a" * 39,
                "example/action@" + "g" * 40,
                "example/action@" + "a" * 41,
                "example/action",
                "docker://example/image:latest",
                "${{ inputs.action }}",
                None,
            ):
                with self.subTest(path=path, uses=uses):
                    changed = self.change(
                        path,
                        lambda d, name=name, uses=uses: d["jobs"][name]["steps"].append(
                            {"uses": uses}
                        ),
                    )
                    self.assertIn("step_uses_unpinned", self.check(changed))

    def test_local_step_action_must_already_be_in_required_base(self):
        path = ".github/workflows/quality.yml"

        def add_local(d):
            d["jobs"]["source-quality"]["steps"].append({"uses": "./.github/actions/example"})

        changed = self.change(path, add_local)
        self.assertEqual(["required_job_changed"], self.check(changed))
        self.assertEqual([], policy.validate(changed, changed))

    def test_checkout_cannot_persist_credentials(self):
        for value in (True, "false", None):
            with self.subTest(value=value):

                def mutate(d, value=value):
                    step = next(
                        s
                        for s in d["jobs"]["source-quality"]["steps"]
                        if s.get("uses", "").lower().startswith("actions/checkout@")
                    )
                    step["with"]["persist-credentials"] = value

                changed = self.change(".github/workflows/quality.yml", mutate)
                self.assertIn("checkout_credentials_refused", self.check(changed))

    def test_checkout_credentials_are_checked_case_insensitively(self):
        for uses in ("Actions/checkout@", "actions/Checkout@", "ACTIONS/CHECKOUT@"):
            with self.subTest(uses=uses):

                def mutate(d, uses=uses):
                    step = d["jobs"]["source-quality"]["steps"][0]
                    step["uses"] = uses + "a" * 40
                    step["with"]["persist-credentials"] = True

                self.assertIn(
                    "checkout_credentials_refused",
                    self.check(self.change(".github/workflows/quality.yml", mutate)),
                )

    def test_malformed_checkout_inputs_refuse_without_raising(self):
        for value in (None, [], 1, "invalid"):
            with self.subTest(value=value):
                changed = self.change(
                    ".github/workflows/quality.yml",
                    lambda d, value=value: d["jobs"]["source-quality"]["steps"][0].update(
                        {"with": value}
                    ),
                )
                self.assertIn("step_mapping_required", self.check(changed))

    def test_malformed_required_jobs_refuse_without_raising(self):
        for value in (None, [], 1, "invalid"):
            with self.subTest(value=value):
                changed = self.change(
                    ".github/workflows/quality.yml", lambda d, value=value: d.update(jobs=value)
                )
                self.assertIn("job_mapping_required", self.check(changed))

    def test_unexpected_validation_exception_publishes_generic_failure(self):
        event = {
            "pull_request": {
                "base": {"ref": "main", "repo": {"full_name": "example/project"}},
                "head": {"sha": "a" * 40},
            }
        }
        for error in (AttributeError, RuntimeError):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory:
                event_file = Path(directory) / "event.json"
                event_file.write_text(json.dumps(event))
                output = io.StringIO()
                with (
                    patch.object(
                        policy.sys, "argv", ["ci_policy.py", "--event-file", str(event_file)]
                    ),
                    patch.dict(policy.os.environ, {"GITHUB_REPOSITORY": "example/project"}),
                    patch.object(policy, "local_workflows", return_value=self.workflows),
                    patch.object(policy, "remote_workflows", return_value=self.workflows),
                    patch.object(policy, "validate", side_effect=error("private diagnostic")),
                    patch.object(policy, "github_json", return_value={"id": 1}) as api,
                    redirect_stdout(output),
                ):
                    self.assertEqual(1, policy.main())
                endpoint, body = api.call_args.args
                self.assertEqual("/repos/example/project/check-runs", endpoint)
                self.assertEqual("a" * 40, body["head_sha"])
                self.assertEqual("failure", body["conclusion"])
                self.assertEqual("Policy refused: inspection_failed", body["output"]["summary"])
                self.assertEqual("CI policy refused: inspection_failed\n", output.getvalue())

    def test_execution_jobs_require_nonempty_step_lists(self):
        for value in (None, [], {}, {"run": "true"}, 1, "invalid"):
            with self.subTest(value=value):
                changed = self.change(
                    ".github/workflows/quality.yml",
                    lambda d, value=value: d["jobs"]["source-quality"].update(steps=value),
                )
                self.assertIn("steps_required", self.check(changed))
        changed = self.change(
            ".github/workflows/quality.yml", lambda d: d["jobs"]["source-quality"].pop("steps")
        )
        self.assertIn("steps_required", self.check(changed))

    def test_job_harness_rejects_nonlist_steps(self):
        baseline = {"example": {"runs-on": "ubuntu-24.04", "steps": [{"run": "true"}]}}
        for value in (None, {}, 1, "invalid"):
            with self.subTest(value=value):
                candidate = {"example": {"runs-on": "ubuntu-24.04", "steps": value}}
                self.assertTrue(policy.job_harness_changed(candidate, baseline))

    def test_secrets_references_cannot_hide_after_format_braces_or_in_bare_conditions(self):
        for step in (
            {"run": "echo ${{ format('{0}', '') || secrets.X }}"},
            {"run": "echo ${{ format('{0}', '') ||\n secrets['X'] }}"},
            {"run": "true", "if": "secrets.X != ''"},
            {"run": "true", "if": "secrets['X'] != ''"},
        ):
            with self.subTest(step=step):
                changed = self.change(
                    ".github/workflows/quality.yml",
                    lambda d, step=step: d["jobs"]["source-quality"]["steps"].append(step),
                )
                self.assertIn("secrets_refused", self.check(changed))

    def test_benign_secrets_comment_and_unrelated_expression_pass(self):
        changed = self.change(
            ".github/workflows/quality.yml",
            lambda d: d["jobs"]["source-quality"]["steps"].append(
                {"run": "# No secrets.X are used here\necho ${{ github.sha }}\n# secrets['X']"}
            ),
        )
        self.assertEqual([], self.check(changed))

    def test_step_action_references_require_clean_local_paths_or_github_sha_pins(self):
        for uses in (
            "docker://alpine:latest@" + "a" * 40,
            "arbitrary@" + "a" * 40,
            "https://example.org/action@" + "a" * 40,
            "./action@" + "a" * 40,
            "./../x",
            "./action/../x",
            "./action@v1",
            "./action ",
            "./action\n",
            "./action\t",
        ):
            with self.subTest(uses=uses):
                changed = self.change(
                    ".github/workflows/quality.yml",
                    lambda d, uses=uses: d["jobs"]["source-quality"]["steps"].append(
                        {"uses": uses}
                    ),
                )
                self.assertIn("step_uses_unpinned", self.check(changed))

    def test_clean_step_action_references_pass(self):
        for uses in (
            "example/action@" + "a" * 40,
            "Example/action/sub-directory@" + "A" * 40,
            "./.github/actions/example",
            "./action/sub-directory",
        ):
            with self.subTest(uses=uses):
                changed = self.change(
                    ".github/workflows/quality.yml",
                    lambda d, uses=uses: d["jobs"]["source-quality"]["steps"].append(
                        {"uses": uses}
                    ),
                )
                self.assertEqual([], policy.validate(changed, changed))

    def test_nonfree_root_fields_and_unknown_fields_cannot_change(self):
        for key, value in (("run-name", "candidate"), ("future-harness-option", True)):
            with self.subTest(key=key):
                changed = self.change(
                    ".github/workflows/quality.yml",
                    lambda d, key=key, value=value: d.update({key: value}),
                )
                self.assertEqual(["required_workflow_changed"], self.check(changed))

    def test_nonfree_job_concurrency_and_unknown_fields_cannot_change(self):
        for key, value in (
            ("concurrency", {"group": "another-job", "cancel-in-progress": True}),
            ("future-harness-option", True),
        ):
            with self.subTest(key=key):
                changed = self.change(
                    ".github/workflows/quality.yml",
                    lambda d, key=key, value=value: d["jobs"]["source-quality"].update(
                        {key: value}
                    ),
                )
                self.assertEqual(["required_job_changed"], self.check(changed))

    def test_event_normalization_does_not_change_unknown_job_fields(self):
        path = ".github/workflows/quality.yml"
        self.workflows = self.change(
            path, lambda d: d["jobs"]["source-quality"].update(on="pull_request")
        )
        changed = self.change(
            path, lambda d: d["jobs"]["source-quality"].update(on=["pull_request"])
        )
        self.assertEqual(["required_job_changed"], self.check(changed))

    def test_nonfree_root_and_job_fields_cannot_be_removed(self):
        path = ".github/workflows/quality.yml"
        self.workflows = self.change(path, lambda d: d.update({"run-name": "trusted"}))
        self.workflows = self.change(
            path, lambda d: d["jobs"]["source-quality"].update(concurrency={"group": "trusted"})
        )
        changed = self.change(path, lambda d: d.pop("run-name"))
        self.assertEqual(["required_workflow_changed"], self.check(changed))
        changed = self.change(path, lambda d: d["jobs"]["source-quality"].pop("concurrency"))
        self.assertEqual(["required_job_changed"], self.check(changed))

    def test_run_step_hollowing_and_other_step_fields_are_free(self):
        changed = self.change(
            ".github/workflows/quality.yml",
            lambda d: d["jobs"]["source-quality"].update(
                steps=[
                    {
                        "run": "true",
                        "id": "replacement",
                        "shell": "bash",
                        "working-directory": ".",
                        "continue-on-error": True,
                        "timeout-minutes": 1,
                        "future-step-option": "free",
                    }
                ]
            ),
        )
        self.assertEqual([], self.check(changed))

    def test_event_syntax_is_normalized_before_harness_comparison(self):
        path = ".github/workflows/quality.yml"
        self.workflows = self.change(path, lambda d: d.update(on="pull_request"))
        for value in (["pull_request"], {"pull_request": None}):
            with self.subTest(value=value):
                self.assertEqual(
                    [], self.check(self.change(path, lambda d, value=value: d.update(on=value)))
                )

    def test_lint_actions_rejects_a_repository_variable_runner(self):
        workflows = self.change(
            ".github/workflows/lint-actions.yml",
            lambda doc: doc["jobs"]["lint-actions"].update(
                {"runs-on": "${{ fromJSON(vars.CI_RUNS_ON || '\"ubuntu-24.04\"') }}"}
            ),
        )
        self.assertIn("runner_route_refused", self.check(workflows))

    def test_required_root_environment_and_shell_cannot_weaken_jobs(self):
        for key, value in [
            ("env", {"PYTEST_ADDOPTS": "--collect-only"}),
            ("defaults", {"run": {"shell": "echo {0}"}}),
        ]:
            changed = self.change(
                ".github/workflows/quality.yml",
                lambda d, key=key, value=value: d.update({key: value}),
            )
            self.assertIn("required_workflow_changed", self.check(changed))

    def test_dynamic_and_nested_self_hosted_routes_fail(self):
        for runner in [
            "self-hosted",
            ["self-hosted", "linux"],
            "${{ matrix.runner }}",
            {"group": "shared"},
        ]:
            with self.subTest(runner=runner):
                extra = {
                    "on": "pull_request",
                    "permissions": {"contents": "read"},
                    "jobs": {"hostile": {"runs-on": runner, "steps": [{"run": "true"}]}},
                }
                workflows = dict(self.workflows)
                workflows[".github/workflows/nested/hostile.yaml"] = policy.yaml.safe_dump(
                    extra
                ).encode()
                self.assertIn("runner_route_refused", self.check(workflows))

    def test_privilege_and_event_escalation_fail(self):
        for mutate, code in [
            (
                lambda d: d.update(permissions={"contents": "write"}),
                "token_permissions_refused",
            ),
            (lambda d: d.update(on={"pull_request_target": None}), "event_refused"),
            (
                lambda d: d["jobs"]["source-quality"].update(secrets="inherit"),
                "secrets_refused",
            ),
        ]:
            with self.subTest(code=code):
                self.assertIn(
                    code,
                    self.check(self.change(".github/workflows/quality.yml", mutate)),
                )

    def test_schedule_event_is_allowed_outside_release_workflows(self):
        changed = self.change(
            ".github/workflows/delivery-writer.yml",
            lambda d: d.update(on={"schedule": [{"cron": "17 3 * * *"}]}),
        )
        self.assertEqual([], self.check(changed))
        release_scheduled = self.change(
            ".github/workflows/beta.yml",
            lambda d: d.update(
                on={"workflow_dispatch": None, "schedule": [{"cron": "17 3 * * *"}]}
            ),
        )
        self.assertIn("release_event_refused", self.check(release_scheduled))

    def test_required_triggers_allow_only_narrow_additions(self):
        additions = {
            "push": {"branches": ["main"]},
            "schedule": [{"cron": "17 3 * * *"}],
            "workflow_dispatch": None,
        }
        for path in policy.REQUIRED:
            self.workflows = self.change(path, lambda d: d.update(on="pull_request"))
            for added in [{key: value} for key, value in additions.items()] + [additions]:
                with self.subTest(path=path, added=added):
                    changed = self.change(
                        path, lambda d, added=added: d.update(on={"pull_request": None, **added})
                    )
                    self.assertEqual([], self.check(changed))

    def test_required_trigger_changes_still_refuse(self):
        path = ".github/workflows/container.yml"
        for name, value in [
            ("push", None),
            ("push", {"branches": ["other"]}),
            ("push", {"branches": ["main", "other"]}),
            ("push", {"branches": ["main"], "paths": ["backend/**"]}),
            ("workflow_run", {"workflows": ["other"], "types": ["completed"]}),
            ("pull_request_target", None),
        ]:
            with self.subTest(name=name, value=value):
                changed = self.change(path, lambda d, name=name, value=value: d["on"].update({name: value}))
                self.assertIn("required_workflow_changed", self.check(changed))
        for name in ("pull_request", "workflow_call", "workflow_dispatch"):
            changed = self.change(path, lambda d, name=name: d["on"].pop(name))
            self.assertIn("required_workflow_changed", self.check(changed))
            if name == "pull_request":
                self.assertIn("required_trigger_changed", self.check(changed))
        for filters in ({"paths": ["backend/**"]}, {"branches": ["main"]}):
            changed = self.change(path, lambda d, filters=filters: d["on"].update(pull_request=filters))
            self.assertIn("required_trigger_changed", self.check(changed))

    def test_existing_required_event_configuration_remains_locked(self):
        path = ".github/workflows/quality.yml"
        changed = self.change(path, lambda d: d["on"].update(push={"branches": ["other"]}))
        self.assertIn("required_workflow_changed", self.check(changed))
        changed = self.change(path, lambda d: d["on"].pop("push"))
        self.assertIn("required_workflow_changed", self.check(changed))

    def test_release_trigger_restrictions_are_unchanged(self):
        for path in policy.RELEASES:
            for added in ({"push": {"branches": ["main"]}}, {"schedule": [{"cron": "17 3 * * *"}]}):
                with self.subTest(path=path, added=added):
                    changed = self.change(path, lambda d, added=added: d["on"].update(added))
                    self.assertIn("release_event_refused", self.check(changed))

    def test_required_status_cannot_be_skipped_or_shadowed(self):
        def skip(d):
            d["on"]["pull_request"] = {"paths": ["backend/**"]}

        self.assertIn(
            "required_trigger_changed",
            self.check(self.change(".github/workflows/quality.yml", skip)),
        )

        def hide(d):
            d["jobs"]["source-quality"]["if"] = "false"

        self.assertIn(
            "required_job_changed",
            self.check(self.change(".github/workflows/quality.yml", hide)),
        )
        workflows = dict(self.workflows)
        workflows[".github/workflows/shadow.yml"] = (
            b'on: pull_request\npermissions: {contents: read}\njobs:\n  fake:\n    name: source-quality\n    runs-on: ubuntu-24.04\n    steps: [{run: "true"}]\n'
        )
        self.assertIn("required_status_shadowed", self.check(workflows))

    def test_policy_job_check_cannot_be_shadowed_by_id_or_display_name(self):
        for path in (".github/workflows/quality.yml", ".github/workflows/shadow.yml"):
            for value in ("Inspect CI policy", " inspect ci policy ", "INSPECT CI POLICY", "ci-policy"):
                for field in ("id", "name"):
                    with self.subTest(path=path, value=value, field=field):
                        job = {"runs-on": "ubuntu-24.04", "steps": [{"run": "true"}]}
                        key = value if field == "id" else "another-policy"
                        if field == "name":
                            job["name"] = value
                        workflows = dict(self.workflows)
                        document = (
                            policy.parse(workflows[path]) if path in workflows else
                            {"on": "pull_request", "permissions": {"contents": "read"}, "jobs": {}}
                        )
                        document["jobs"][key] = job
                        workflows[path] = policy.yaml.safe_dump(document).encode()
                        self.assertIn("required_status_shadowed", self.check(workflows))

    def test_trusted_policy_workflows_own_job_check_name_is_accepted(self):
        document = policy.parse(self.workflows[policy.POLICY])
        self.assertEqual("Inspect CI policy", document["jobs"]["ci-policy"]["name"])
        self.assertEqual([], self.check())

    def test_duplicate_keys_aliases_unknown_tags_and_boolean_on_fail(self):
        self.assertEqual({"on": "pull_request"}, policy.parse(b"on: pull_request"))
        for content in [
            b"jobs: {}\njobs: {}",
            b"jobs: &x {foo: *x}",
            b"jobs: !!python/object:os.system {}",
            b"jobs: {1: invalid}",
        ]:
            with self.subTest(content=content), self.assertRaises(policy.Refused):
                policy.parse(content)

    def test_policy_workflow_candidate_cannot_execute_candidate(self):
        workflows = self.change(
            ".github/workflows/ci-policy.yml",
            lambda d: d["jobs"]["ci-policy"]["steps"].append({"run": "echo hostile"}),
        )
        self.assertIn("trusted_policy_workflow_changed", self.check(workflows))

    def test_removed_workflow_and_excess_files_fail(self):
        workflows = dict(self.workflows)
        workflows.pop(".github/workflows/quality.yml")
        self.assertIn("required_workflow_missing", self.check(workflows))
        with self.assertRaises(policy.Refused):
            policy.validate_tree({"truncated": True, "tree": []})
        with self.assertRaises(policy.Refused):
            policy.validate_tree(
                {
                    "tree": [
                        {
                            "path": ".github/workflows",
                            "mode": "120000",
                            "type": "blob",
                            "sha": "a" * 40,
                        }
                    ]
                }
            )

    def test_symlink_workflow_is_refused(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".github/workflows").mkdir(parents=True)
            (root / "outside.yml").write_text("on: pull_request")
            (root / ".github/workflows/escape.yml").symlink_to(root / "outside.yml")
            with self.assertRaises(policy.Refused):
                policy.local_workflows(root)

    def test_candidate_scripts_are_never_loaded_during_remote_inspection(self):
        import base64

        content = b"on: pull_request\npermissions: {contents: read}\njobs: {}"
        tree = {
            "tree": [
                {
                    "path": "scripts/ci_policy.py",
                    "type": "blob",
                    "mode": "100644",
                    "size": 20,
                    "sha": "a" * 40,
                },
                {
                    "path": ".github/workflows/check.yml",
                    "type": "blob",
                    "mode": "100644",
                    "size": len(content),
                    "sha": "b" * 40,
                },
            ]
        }
        blob = {
            "encoding": "base64",
            "size": len(content),
            "content": base64.b64encode(content).decode(),
        }
        with patch.object(policy, "github_json", side_effect=[tree, blob]) as api:
            result = policy.remote_workflows("example/project", "c" * 40)
        self.assertEqual({".github/workflows/check.yml": content}, result)
        self.assertEqual(2, api.call_count)
        self.assertTrue(api.call_args_list[1].args[0].endswith("b" * 40))

    def test_status_is_published_on_candidate_head_for_success_and_failure(self):
        for errors, conclusion in [
            ([], "success"),
            (["runner_route_refused"], "failure"),
        ]:
            with self.subTest(conclusion=conclusion):
                with patch.object(policy, "github_json", return_value={"id": 1}) as api:
                    policy.publish_check("example/project", "d" * 40, errors)
                endpoint, body = api.call_args.args
                self.assertEqual("/repos/example/project/check-runs", endpoint)
                self.assertEqual("d" * 40, body["head_sha"])
                self.assertEqual("ci-policy", body["name"])
                self.assertEqual(conclusion, body["conclusion"])

    def test_status_identity_and_redirects_fail_closed(self):
        for repository, revision in [
            ("example/project", "HEAD"),
            ("example/project/extra", "d" * 40),
        ]:
            with self.assertRaises(policy.Refused):
                policy.publish_check(repository, revision, [])
        with self.assertRaises(policy.Refused):
            policy.NoRedirect().redirect_request(
                None, None, 302, "redirect", {}, "https://example.org"
            )

    def test_budget_and_malformed_blob_fail_closed(self):
        with self.assertRaises(policy.Refused):
            policy.parse(b"x" * (policy.MAX_FILE + 1))
        with self.assertRaises(policy.Refused):
            policy.validate({str(i): b"" for i in range(policy.MAX_WORKFLOWS + 1)}, {})
        entry = {
            "path": ".github/workflows/a.yml",
            "type": "blob",
            "mode": "100644",
            "size": 1,
            "sha": "a" * 40,
        }
        with (
            patch.object(
                policy,
                "github_json",
                side_effect=[
                    {"tree": [entry]},
                    {"size": 1, "encoding": "base64", "content": "YWI="},
                ],
            ),
            self.assertRaises(policy.Refused),
        ):
            policy.remote_workflows("example/project", "b" * 40)


if __name__ == "__main__":
    unittest.main()
