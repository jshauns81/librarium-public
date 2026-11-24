"""Select container tiers and report the required result without hiding failures."""

import os
import subprocess
import sys

from changed_areas import classify


def evaluate(found, changes, code, current, upgrade):
    candidate = found.get("candidate_container")
    rehearsal = found.get("populated_upgrade")
    valid = (
        type(candidate) is bool
        and type(rehearsal) is bool
        and (not rehearsal or candidate)
        and changes == "success"
        and code == str(candidate).lower()
    )
    rows = [("classification", "succeeded" if valid else "failed")]
    for name, selected, result, deferred_result in (
        ("candidate-container", candidate, current, "skipped"),
        # With the locked dependency harness, a deferred rehearsal job starts after a build.
        ("populated-upgrade", rehearsal, upgrade, "success" if candidate else "skipped"),
    ):
        if result in ("failure", "cancelled"):
            state = "failed"
        elif not result or (selected and result == "skipped"):
            state = "missing"
        elif selected and result == "success":
            state = "succeeded"
        elif selected is False and result == deferred_result and valid:
            state = "deferred"
        else:
            state = "unexpected"
        rows.append((name, state))
    return valid and all(state in ("succeeded", "deferred") for _, state in rows), rows


def summary(rows):
    text = "| Tier | State |\n|---|---|\n" + "".join(
        f"| {name} | {state} |\n" for name, state in rows
    )
    text += (
        "\nDeferred means classification did not select acceptance for this PR; "
        "main pushes, manual runs and beta calls select both tiers. "
        "Failed, missing and unexpected results fail the required gate.\n"
    )
    print(text)
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as target:
        target.write(text)


def main(mode, base):
    try:
        found = classify(base)
    except (OSError, subprocess.CalledProcessError):
        if mode == "require":
            summary([("classification", "failed")])
        return 1
    if mode == "classify":
        for name in ("candidate_container", "populated_upgrade"):
            print(f"{name}={str(found[name]).lower()}")
        # Preserve the required workflow's locked job output and condition.
        print(f"code={str(found['candidate_container']).lower()}")
        return 0
    passed, rows = evaluate(
        found,
        os.environ.get("CHANGES_RESULT"),
        os.environ.get("CODE_CHANGED"),
        os.environ.get("CURRENT_IMAGE_RESULT"),
        os.environ.get("POPULATED_UPGRADE_RESULT"),
    )
    summary(rows)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""))
