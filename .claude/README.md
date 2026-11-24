# Claude Code guide

Read [AGENTS.md](../AGENTS.md), imported through root `CLAUDE.md`, then the shared
read order. Verify actual workspace binding and source provenance. Provider-specific
guidance never replaces the product's shared contracts.

Load operational handoffs and installed-tool details from
[private context](../docs/agent-environment.md). Keep client configuration, personal
paths, service endpoints and raw audit evidence outside GitHub. Use the installed
skills and current harness tools; do not copy a whole agent home or replace native
plugins. Preserve other agents' edits, serialize shared-file changes, and record
status updates by adding a new file under `docs/status/` rather than editing
`docs/status.md` or another PR's entry.
