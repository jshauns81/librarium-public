# Unified beta candidate preparation, 2026-11-01

`compose.registry-workspace.yaml` selects the existing native book, preserved-file
and assessment roles through one deployment entry. `compose.runtime.yaml` keeps
owner initialization separate from web/worker database credentials, using the
existing runtime grant provisioner. Resolved configuration validation now accepts
that split while checking role/database bindings and every production database
credential for overlap. [Verification](../unified-beta-candidate.tdd.md) records the
scope; actual Compose/image acceptance and target readiness remain required.
Release copy describes one continuous book workflow. No beta is newly installed,
and optional-role activation retains its target kernel/storage and concrete scope.
