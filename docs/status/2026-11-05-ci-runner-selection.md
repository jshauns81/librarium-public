# CI runner selection, 2026-11-05

The custom runner provisioning design is abandoned. The [CI contract](../ci.md)
now routes source, container, writer and release jobs through the repository
variable `CI_RUNS_ON`, with a one-variable hosted fallback. The privileged
trusted-base policy job stays hosted. Frontend-only changes skip heavy container
acceptance; the required aggregate result still reports. Synthetic writer
acceptance now triggers on pull requests only when writer-related paths change,
with a nightly `schedule` on `main` as the regression net for unrelated changes
and `workflow_dispatch` retained; backend-only frontend skips in source quality
are retained. Repository routing is under review; actual pool execution and the
trusted-policy transition remain acceptance limits. No registry, publishing or
production behavior is changed.
